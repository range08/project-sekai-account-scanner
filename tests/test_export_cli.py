from __future__ import annotations

import json
from pathlib import Path

import pytest

from pjsk_scanner.cli import main
from pjsk_scanner.errors import DeviceDiscoveryError
from pjsk_scanner.export.json_exporter import export_account, load_account
from pjsk_scanner.normalize.account import normalize_suite_payload


def test_json_export_import_round_trip(master: object, tmp_path: Path) -> None:
    suite = json.loads(
        (Path(__file__).parent / "fixtures" / "suite-user.json").read_text(
            encoding="utf-8"
        )
    )
    account = normalize_suite_payload(suite, master)  # type: ignore[arg-type]
    output = export_account(account, tmp_path / "account.json")

    imported = load_account(output)
    assert imported.to_dict() == account.to_dict()
    assert output.stat().st_mode & 0o077 == 0


def test_cli_help_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as captured:
        main(["--help"])
    assert captured.value.code == 0
    output = capsys.readouterr().out
    assert "master" in output
    assert "credentials" in output
    assert "doctor" in output


def test_credentials_and_doctor_help_smoke(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for command in (
        ["credentials", "discover", "--help"],
        ["doctor", "--help"],
    ):
        with pytest.raises(SystemExit) as captured:
            main(command)
        assert captured.value.code == 0
        output = capsys.readouterr().out
        assert "--env-file" in output
    assert "--adb" in output


def test_cli_raw_import_and_report_smoke(
    master_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "account.json"
    fixture = Path(__file__).parent / "fixtures" / "suite-user.json"
    assert (
        main(
            [
                "import",
                "raw",
                str(fixture),
                "--master-dir",
                str(master_dir),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.is_file()
    assert main(["report", str(output)]) == 0


def test_cli_reports_invalid_suite_as_nonzero_without_traceback(
    master_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("[]", encoding="utf-8")
    status = main(
        [
            "import",
            "raw",
            str(path),
            "--master-dir",
            str(master_dir),
            "--output",
            str(tmp_path / "out.json"),
        ]
    )

    assert status == 1
    assert "Traceback" not in capsys.readouterr().err


def test_api_cli_checks_protocol_configuration_before_upstream_loading(
    master_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
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
        monkeypatch.setenv(name, f"synthetic-{name.lower()}")
    monkeypatch.delenv("AES_KEY", raising=False)
    monkeypatch.delenv("AES_IV", raising=False)
    monkeypatch.setattr(
        "pjsk_scanner.backends.api.extractor.load_upstream_modules",
        lambda: pytest.fail("protocol preflight must happen before network setup"),
    )

    status = main(
        [
            "import",
            "api",
            "--region",
            "kr",
            "--master-dir",
            str(master_dir),
            "--output",
            str(tmp_path / "account.json"),
            "--env-file",
            str(tmp_path / "missing.env"),
        ]
    )

    assert status == 1
    error = capsys.readouterr().err
    assert "AES_KEY, AES_IV" in error
    assert "synthetic-" not in error


def test_credential_discovery_failure_does_not_write_partial_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"

    def fail_discovery(**_kwargs: object) -> dict[str, str]:
        raise DeviceDiscoveryError(
            "duplicate synthetic fields; refusing to infer access token"
        )

    monkeypatch.setattr("pjsk_scanner.cli.load_env_file", lambda _path: {})
    monkeypatch.setattr("pjsk_scanner.cli.discover_kr_environment", fail_discovery)
    monkeypatch.setattr(
        "pjsk_scanner.cli.write_private_env",
        lambda *_args, **_kwargs: pytest.fail("must not write partial credentials"),
    )

    status = main(
        [
            "credentials",
            "discover",
            "--region",
            "kr",
            "--env-file",
            str(env_file),
        ]
    )

    assert status == 1
    assert not env_file.exists()
    error = capsys.readouterr().err
    assert "synthetic fields" in error
    assert "synthetic-secret" not in error
