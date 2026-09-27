from __future__ import annotations

import json
from pathlib import Path

import pytest

from pjsk_scanner.cli import main
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
    assert "master" in capsys.readouterr().out


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
