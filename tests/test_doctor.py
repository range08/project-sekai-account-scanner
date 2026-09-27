from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from pjsk_scanner import doctor
from pjsk_scanner.backends.api.credentials import ApiCredentials
from pjsk_scanner.backends.api.extractor import ApiExtractor
from pjsk_scanner.errors import ApiBackendError

_ACCOUNT_ENV = {
    "SEKAI_KR_SDK_OPEN_ID": "synthetic-open-id",
    "SEKAI_KR_ACCESS_TOKEN": "synthetic-access-token",
    "SEKAI_KR_DEVICE_ID": "synthetic-device-id",
    "SEKAI_KR_INSTALL_ID": "synthetic-install-id",
    "SEKAI_KR_USER_AGENT": "synthetic-user-agent",
    "SEKAI_KR_DEVICE_MODEL": "synthetic-model",
    "SEKAI_KR_OS_VERSION": "synthetic-os",
    "AES_KEY": "00112233445566778899aabbccddeeff",
    "AES_IV": "00112233445566778899aabbccddeeff",
}


class _FakeDevice:
    serial = "emulator-test"

    def verify_package_and_root(self) -> None:
        return None


def _stub_local_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    master_dir = tmp_path / "master"
    shutil.copytree(Path(__file__).parent / "fixtures" / "master", master_dir)
    output_dir = tmp_path / "output"
    monkeypatch.setattr(doctor, "load_upstream_modules", lambda: (object, object()))
    monkeypatch.setattr(doctor, "resolve_adb_executable", lambda _adb=None: "adb")
    monkeypatch.setattr(
        doctor, "select_device", lambda *_args, **_kwargs: _FakeDevice()
    )
    return master_dir, output_dir


def test_doctor_checks_local_setup_without_constructing_api_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in _ACCOUNT_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(doctor, "load_env_file", lambda _path: {})
    master_dir, output_dir = _stub_local_dependencies(monkeypatch, tmp_path)

    def forbidden_network(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("doctor must not make HTTP requests")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_network)
    monkeypatch.setattr(
        ApiExtractor,
        "extract",
        lambda *_args, **_kwargs: pytest.fail("doctor must not extract an account"),
    )
    checks = doctor.run_doctor(
        env_file=tmp_path / ".env",
        master_dir=master_dir,
        output_dir=output_dir,
        adb="adb",
    )

    assert all(check.ok for check in checks)
    report = doctor.format_doctor(checks)
    assert "no Project SEKAI network requests" in report
    assert "synthetic-access-token" not in report
    assert "emulator-test" not in report


def test_doctor_reports_missing_credentials_without_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in (*_ACCOUNT_ENV, "APP_VER", "APP_HASH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(doctor, "load_env_file", lambda _path: {})
    master_dir, output_dir = _stub_local_dependencies(monkeypatch, tmp_path)

    checks = doctor.run_doctor(
        env_file=tmp_path / ".env",
        master_dir=master_dir,
        output_dir=output_dir,
        adb="adb",
    )
    by_name = {check.name: check for check in checks}

    assert not by_name["KR account credentials"].ok
    assert not by_name["AES protocol config"].ok
    assert "synthetic" not in doctor.format_doctor(checks)


def test_api_credentials_rejects_missing_discovered_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "SEKAI_KR_SDK_OPEN_ID",
        "SEKAI_KR_ACCESS_TOKEN",
        "SEKAI_KR_DEVICE_ID",
        "SEKAI_KR_INSTALL_ID",
        "SEKAI_KR_USER_AGENT",
        "SEKAI_KR_DEVICE_MODEL",
        "SEKAI_KR_OS_VERSION",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ApiBackendError, match="Missing required KR credential"):
        ApiCredentials.from_environment()
