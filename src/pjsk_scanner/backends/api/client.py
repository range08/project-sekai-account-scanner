"""Load the pinned upstream client checkout without copying protocol code."""

from __future__ import annotations

import importlib
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pjsk_scanner.errors import ApiBackendError
from pjsk_scanner.utils import RedactionFilter

EXPECTED_SEKAI_CLIENT_COMMIT = "bfae1c53454777bec4107c43295d350e114d7f85"


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


def quiet_upstream_logger() -> logging.Logger:
    """Give upstream a sink that cannot print request headers or token data."""
    logger = logging.Logger("pjsk_scanner.upstream", level=logging.CRITICAL + 1)
    logger.propagate = False
    logger.addFilter(RedactionFilter())
    logger.addHandler(logging.NullHandler())
    return logger
