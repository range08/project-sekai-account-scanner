"""Private, dependency-free `.env` loading and writing."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from pjsk_scanner.errors import ScannerError

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env_text(contents: str) -> dict[str, str]:
    """Parse simple KEY=value settings without evaluating shell expressions."""
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(contents.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if not separator or not _NAME.fullmatch(name):
            raise ScannerError(f"Invalid .env syntax at line {line_number}")
        values[name] = _parse_env_value(raw_value.strip(), line_number)
    return values


def load_env_file(path: str | Path = ".env") -> dict[str, str]:
    """Load values from a local file, keeping explicitly-set process values."""
    env_path = Path(path)
    if env_path.is_symlink():
        raise ScannerError("Refusing to load credentials through a symbolic link")
    try:
        contents = env_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError):
        raise ScannerError("Could not read the local environment file") from None
    if os.name != "nt" and stat.S_IMODE(env_path.stat().st_mode) & 0o077:
        raise ScannerError(
            "Local environment file permissions are too broad; run chmod 600"
        )
    values = parse_env_text(contents)
    for name, value in values.items():
        os.environ.setdefault(name, value)
    return values


def write_private_env(values: Mapping[str, str], path: str | Path = ".env") -> Path:
    """Atomically merge values into an ignored config file with owner-only mode."""
    destination = Path(path).expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ScannerError("Refusing to write credentials through a symbolic link")
    _require_git_ignored(destination)

    existing: dict[str, str] = {}
    if destination.exists():
        try:
            existing = parse_env_text(destination.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            raise ScannerError("Could not update the local environment file") from None
    for name, value in values.items():
        if not _NAME.fullmatch(name) or "\n" in value or "\r" in value:
            raise ScannerError("Cannot write malformed local configuration")
        existing[name] = value

    content = "".join(
        f"{name}={json.dumps(value, ensure_ascii=True)}\n"
        for name, value in sorted(existing.items())
    )
    temporary_name: str | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    except OSError:
        raise ScannerError(
            "Could not securely write the local environment file"
        ) from None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return destination


def _parse_env_value(value: str, line_number: int) -> str:
    if value.startswith('"'):
        try:
            parsed, end = json.JSONDecoder().raw_decode(value)
        except json.JSONDecodeError:
            raise ScannerError(
                f"Invalid quoted .env value at line {line_number}"
            ) from None
        trailing = value[end:].strip()
        if not isinstance(parsed, str) or (trailing and not trailing.startswith("#")):
            raise ScannerError(f"Invalid quoted .env value at line {line_number}")
        return parsed
    if value.startswith("'"):
        closing = value.find("'", 1)
        if closing < 0:
            raise ScannerError(f"Invalid quoted .env value at line {line_number}")
        trailing = value[closing + 1 :].strip()
        if trailing and not trailing.startswith("#"):
            raise ScannerError(f"Invalid quoted .env value at line {line_number}")
        return value[1:closing]
    return value.split(" #", 1)[0].rstrip()


def _require_git_ignored(path: Path) -> None:
    try:
        root_result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        raise ScannerError(
            "Could not verify that the config file is Git-ignored"
        ) from None
    root = Path(root_result.stdout.strip()).resolve()
    try:
        relative_path = path.resolve().relative_to(root).as_posix()
    except ValueError:
        return
    try:
        ignored = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "check-ignore",
                "--no-index",
                "--quiet",
                "--",
                relative_path,
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        raise ScannerError(
            "Could not verify that the config file is Git-ignored"
        ) from None
    if ignored.returncode != 0:
        raise ScannerError(
            "Refusing to write credentials to a path Git does not ignore"
        )
