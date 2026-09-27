"""Load the pinned upstream client checkout without copying protocol code."""

from __future__ import annotations

import importlib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pjsk_scanner.errors import ApiBackendError
from pjsk_scanner.utils import RedactionFilter

EXPECTED_SEKAI_CLIENT_COMMIT = "bfae1c53454777bec4107c43295d350e114d7f85"
_USER_LOGIN_PATH = re.compile(r"^/user/[0-9]+/login$")
_SUITE_USER_PATH = re.compile(r"^/suite/user/[0-9]+$")


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

    def guarded_call(
        endpoint: str,
        method: str = "get",
        body: str | dict[str, Any] = "",
        retry_policy: Any | None = None,
        *,
        bypass_error_recovery: bool = False,
    ) -> Any:
        del bypass_error_recovery
        path = endpoint.split("?", 1)[0]
        normalized_method = method.lower()
        allowed = (
            (path == "/user/auth" and normalized_method == "post")
            or (_USER_LOGIN_PATH.fullmatch(path) and normalized_method == "post")
            or (_SUITE_USER_PATH.fullmatch(path) and normalized_method == "get")
        )
        if not allowed:
            raise ApiBackendError(
                "Pinned sekai-client attempted a request outside the "
                "authentication and suite-read allowlist"
            )
        return original_call(
            endpoint,
            method,
            body,
            retry_policy,
            bypass_error_recovery=True,
        )

    client.call_pjsk_api = guarded_call


def quiet_upstream_logger() -> logging.Logger:
    """Give upstream a sink that cannot print request headers or token data."""
    logger = logging.Logger("pjsk_scanner.upstream", level=logging.CRITICAL + 1)
    logger.propagate = False
    logger.addFilter(RedactionFilter())
    logger.addHandler(logging.NullHandler())
    return logger
