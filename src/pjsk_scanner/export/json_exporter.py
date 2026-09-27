"""Private-by-default JSON export and validated re-import."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pjsk_scanner.models import NormalizedAccount


def export_account(account: NormalizedAccount, destination: str | Path) -> Path:
    """Write normalized JSON atomically with owner-only file permissions."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(account.to_dict(), ensure_ascii=False, indent=2) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def load_account(source: str | Path) -> NormalizedAccount:
    """Load an exported normalized account JSON file."""
    path = Path(source)
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Account JSON file not found: {path}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(f"Could not read valid account JSON from {path}") from None
    if not isinstance(value, dict):
        raise ValueError("Normalized account must be a JSON object")
    try:
        return NormalizedAccount.from_dict(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid normalized account file: {error}") from None
