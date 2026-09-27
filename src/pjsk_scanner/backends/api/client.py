"""Load the pinned upstream client checkout without copying protocol code."""

from __future__ import annotations

import importlib
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from pjsk_scanner.errors import ApiBackendError
from pjsk_scanner.utils import RedactionFilter

EXPECTED_SEKAI_CLIENT_COMMIT = "bfae1c53454777bec4107c43295d350e114d7f85"
_USER_LOGIN_PATH = re.compile(r"^/user/([0-9]+)/login$")
_SUITE_USER_PATH = re.compile(r"^/suite/user/([0-9]+)$")
_TRANSPORT_PATCH_LOCK = threading.RLock()


def load_upstream_modules() -> tuple[type[Any], ModuleType]:
    """Load APIClient and the upstream account helpers from the pinned checkout."""
    configured_path = os.environ.get("SEKAI_CLIENT_PATH")
    if not configured_path:
        raise ApiBackendError(
            "SEKAI_CLIENT_PATH must point to the pinned sekai-client checkout"
        )
    root = Path(configured_path).expanduser().resolve()
    if not (root / "api_client.py").is_file():
        raise ApiBackendError("SEKAI_CLIENT_PATH does not contain api_client.py")
    try:
        revision_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        raise ApiBackendError(
            "Could not verify the sekai-client checkout revision"
        ) from None
    revision = revision_result.stdout.strip()
    if revision != EXPECTED_SEKAI_CLIENT_COMMIT:
        raise ApiBackendError(
            "sekai-client checkout revision does not match the pinned revision "
            f"{EXPECTED_SEKAI_CLIENT_COMMIT}"
        )

    root_string = str(root)
    if root_string not in sys.path:
        sys.path.insert(0, root_string)
    try:
        api_module = importlib.import_module("api_client")
        accounts_module = importlib.import_module("accounts")
    except ModuleNotFoundError as error:
        missing = error.name or "unknown module"
        raise ApiBackendError(
            f"Could not load sekai-client dependency {missing}; run uv sync --extra api"
        ) from None
    except ImportError:
        raise ApiBackendError(
            "Could not import the pinned sekai-client checkout"
        ) from None
    for module in (api_module, accounts_module):
        module_path = Path(module.__file__ or "").resolve()
        if not module_path.is_relative_to(root):
            raise ApiBackendError(
                "A conflicting API client module is already loaded in this process"
            )
    api_client_type = getattr(api_module, "APIClient", None)
    if not isinstance(api_client_type, type):
        raise ApiBackendError("Pinned sekai-client does not expose APIClient")
    return api_client_type, accounts_module


def validate_read_only_client(client: Any) -> None:
    """Fail closed if the pinned client's read-only auth surface has changed."""
    required_methods = (
        "_authenticate",
        "_apply_auth_headers_and_version_info",
        "fetch_suite_user",
        "call_pjsk_api",
    )
    missing = [
        name for name in required_methods if not callable(getattr(client, name, None))
    ]
    required_state = ("_pending_game_user_id", "_authenticating")
    missing.extend(name for name in required_state if not hasattr(client, name))
    protocol = getattr(client, "protocol", None)
    if not callable(getattr(protocol, "send", None)):
        missing.append("protocol.send")
    if missing:
        methods = ", ".join(missing)
        raise ApiBackendError(
            "Pinned sekai-client is incompatible with read-only extraction; "
            f"missing required API surface: {methods}"
        )


def install_read_only_request_guard(client: Any) -> None:
    """Allow only KR authentication and suite reads through the game API client.

    Recovery is disabled on these calls because the upstream recovery handlers
    can invoke login, agreement, cookie, or version-refresh operations.
    """
    original_call = client.call_pjsk_api
    authenticated_user_id: int | None = None
    login_completed = False
    suite_fetched = False
    request_context: dict[str, Any] = {"active_request": None}

    def guarded_call(
        endpoint: str,
        method: str = "get",
        body: str | dict[str, Any] = "",
        retry_policy: Any | None = None,
        *,
        bypass_error_recovery: bool = False,
    ) -> Any:
        nonlocal authenticated_user_id, login_completed, suite_fetched
        del bypass_error_recovery
        path = endpoint.split("?", 1)[0]
        if not _is_allowed_request(path, method):
            raise ApiBackendError(
                "Pinned sekai-client attempted a request outside the "
                "authentication and suite-read allowlist"
            )
        login_match = _USER_LOGIN_PATH.fullmatch(path)
        suite_match = _SUITE_USER_PATH.fullmatch(path)
        if path == "/user/auth":
            if authenticated_user_id is not None or login_completed or suite_fetched:
                raise ApiBackendError("Read-only authentication flow was repeated")
        elif login_match is not None:
            if (
                authenticated_user_id is None
                or login_match.group(1) != str(authenticated_user_id)
                or login_completed
                or suite_fetched
            ):
                raise ApiBackendError(
                    "Login request did not match the authenticated KR user"
                )
        elif suite_match is not None:
            pending_user_id = getattr(client, "_pending_game_user_id", None)
            if (
                not login_completed
                or authenticated_user_id is None
                or suite_match.group(1) != str(authenticated_user_id)
                or not isinstance(pending_user_id, int)
                or isinstance(pending_user_id, bool)
                or pending_user_id != authenticated_user_id
                or suite_fetched
            ):
                raise ApiBackendError(
                    "Suite request did not match the authenticated KR user"
                )

        normalized_method = method.lower()
        if request_context["active_request"] is not None:
            raise ApiBackendError("Nested game API requests are not allowed")
        request_context["active_request"] = (path, normalized_method)
        try:
            response = original_call(
                endpoint,
                method,
                body,
                retry_policy,
                bypass_error_recovery=True,
            )
        finally:
            request_context["active_request"] = None

        if path == "/user/auth":
            response_user_id = (
                response.get("userId") if isinstance(response, dict) else None
            )
            if (
                not isinstance(response_user_id, int)
                or isinstance(response_user_id, bool)
                or response_user_id <= 0
            ):
                raise ApiBackendError(
                    "KR authentication did not return a valid numeric user ID"
                )
            authenticated_user_id = response_user_id
        elif login_match is not None:
            login_completed = True
        elif suite_match is not None:
            suite_fetched = True
        return response

    client.call_pjsk_api = guarded_call
    _guard_low_level_transport(client.protocol, request_context)


def _is_allowed_request(path: str, method: str) -> bool:
    normalized_method = method.lower()
    return bool(
        (path == "/user/auth" and normalized_method == "post")
        or (_USER_LOGIN_PATH.fullmatch(path) and normalized_method == "post")
        or (_SUITE_USER_PATH.fullmatch(path) and normalized_method == "get")
    )


def _guard_low_level_transport(protocol: Any, request_context: dict[str, Any]) -> None:
    """Block bypasses of the API caller guard and suppress HTTP redirects.

    The pinned transport uses module-level ``requests.request`` and leaves its
    default redirect behavior enabled. Temporarily substitute a narrow proxy in
    that transport module so a server-side redirect cannot turn an allowlisted
    authentication request into an unrelated game request.
    """
    original_send = protocol.send
    send_function = getattr(original_send, "__func__", original_send)
    function_globals = getattr(send_function, "__globals__", None)
    if not isinstance(function_globals, dict):
        raise ApiBackendError(
            "Pinned sekai-client transport is incompatible with the read-only guard"
        )
    requests_module = function_globals.get("requests")
    if requests_module is None:
        raise ApiBackendError(
            "Pinned sekai-client transport is incompatible with the read-only guard"
        )
    request_function = getattr(requests_module, "request", None)
    if not callable(request_function):
        raise ApiBackendError(
            "Pinned sekai-client transport is incompatible with the read-only guard"
        )
    guarded_request_function = cast(Any, request_function)

    class NoRedirectRequests:
        def __getattr__(self, name: str) -> Any:
            return getattr(requests_module, name)

        def request(self, *args: Any, **kwargs: Any) -> Any:
            kwargs["allow_redirects"] = False
            return guarded_request_function(*args, **kwargs)

    no_redirect_requests = NoRedirectRequests()

    def guarded_send(
        endpoint: str,
        method: str,
        data: bytes | None,
        request_id: str | None = None,
    ) -> Any:
        path = endpoint.split("?", 1)[0]
        if not _is_allowed_request(path, method) or request_context.get(
            "active_request"
        ) != (path, method.lower()):
            raise ApiBackendError(
                "Pinned sekai-client attempted an unapproved low-level request"
            )
        with _TRANSPORT_PATCH_LOCK:
            function_globals["requests"] = no_redirect_requests
            try:
                return original_send(endpoint, method, data, request_id)
            finally:
                function_globals["requests"] = requests_module

    protocol.send = guarded_send


def quiet_upstream_logger() -> logging.Logger:
    """Give upstream a sink that cannot print request headers or token data."""
    logger = logging.Logger("pjsk_scanner.upstream", level=logging.CRITICAL + 1)
    logger.propagate = False
    logger.addFilter(RedactionFilter())
    logger.addHandler(logging.NullHandler())
    return logger
