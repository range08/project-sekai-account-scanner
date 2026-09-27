"""Non-network preflight checks for local scanner configuration."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pjsk_scanner.adb import resolve_adb_executable, select_device
from pjsk_scanner.backends.api.client import (
    EXPECTED_SEKAI_CLIENT_COMMIT,
    install_read_only_request_guard,
    load_upstream_modules,
)
from pjsk_scanner.backends.api.credentials import ApiCredentials
from pjsk_scanner.backends.api.protocol import ApiProtocolConfig
from pjsk_scanner.errors import ScannerError
from pjsk_scanner.local_config import load_env_file
from pjsk_scanner.master.downloader import MASTER_FILES
from pjsk_scanner.master.repository import MasterDataRepository


@dataclass(frozen=True)
class Check:
    """One safe, printable doctor result."""

    name: str
    ok: bool
    detail: str


def run_doctor(
    *,
    region: str = "kr",
    env_file: Path = Path(".env"),
    master_dir: Path = Path("data/master"),
    output_dir: Path = Path("data/output"),
    adb: str | None = None,
    serial: str | None = None,
) -> list[Check]:
    """Run local-only checks; this function never constructs an API client."""
    checks: list[Check] = []
    try:
        load_env_file(env_file)
        checks.append(Check("local config", True, "loaded without displaying values"))
    except ScannerError as error:
        checks.append(Check("local config", False, str(error)))

    version_ok = sys.version_info[:2] == (3, 12)
    checks.append(
        Check(
            "Python",
            version_ok,
            f"{sys.version_info.major}.{sys.version_info.minor}"
            + (" (required 3.12)" if not version_ok else ""),
        )
    )

    try:
        ApiCredentials.from_environment()
        checks.append(Check("KR account credentials", True, "all seven fields present"))
    except ScannerError as error:
        checks.append(Check("KR account credentials", False, str(error)))

    try:
        protocol = ApiProtocolConfig.from_environment()
        del protocol
        checks.append(Check("AES protocol config", True, "key and IV formats valid"))
    except ScannerError as error:
        checks.append(Check("AES protocol config", False, str(error)))

    checks.append(
        Check(
            "KR app identity fallback",
            True,
            "APP_VER and APP_HASH configured"
            if os.environ.get("APP_VER") and os.environ.get("APP_HASH")
            else (
                "optional; pinned client will use its KR identity feed where available"
            ),
        )
    )

    try:
        api_client_type, accounts = load_upstream_modules()
        del api_client_type, accounts
        checks.append(
            Check(
                "pinned sekai-client",
                True,
                f"revision {EXPECTED_SEKAI_CLIENT_COMMIT} available",
            )
        )
    except ScannerError as error:
        checks.append(Check("pinned sekai-client", False, str(error)))

    try:
        MasterDataRepository(master_dir, region)
        checks.append(Check("KR master data", True, "all required tables load"))
    except ScannerError as error:
        missing = [
            name for name in MASTER_FILES if not (master_dir / region / name).is_file()
        ]
        detail = (
            "missing or invalid master tables: " + ", ".join(missing)
            if missing
            else str(error)
        )
        checks.append(Check("KR master data", False, detail))

    checks.append(_writable_directory_check("output path", output_dir))
    checks.append(_writable_directory_check("master cache path", master_dir / region))

    guard_available = callable(install_read_only_request_guard)
    checks.append(
        Check(
            "read-only request guard",
            guard_available,
            "authentication and suite-read allowlist available"
            if guard_available
            else "guard implementation unavailable",
        )
    )

    try:
        executable = resolve_adb_executable(adb)
        device = select_device(executable, serial)
        device.verify_package_and_root()
        checks.append(
            Check(
                "ADB device",
                True,
                "KR package installed and root available",
            )
        )
    except ScannerError as error:
        checks.append(Check("ADB device", False, str(error)))
    return checks


def _writable_directory_check(name: str, path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".pjsk-doctor-", dir=path):
            pass
    except OSError:
        return Check(name, False, "directory is not writable")
    return Check(name, True, "directory is writable")


def format_doctor(checks: list[Check]) -> str:
    """Format concise status lines without credential or protocol values."""
    lines = ["Doctor performs no Project SEKAI network requests."]
    lines.extend(
        f"[{'OK' if check.ok else 'FAIL'}] {check.name}: {check.detail}"
        for check in checks
    )
    failed = sum(not check.ok for check in checks)
    lines.append(f"{len(checks) - failed}/{len(checks)} checks passed")
    return "\n".join(lines)
