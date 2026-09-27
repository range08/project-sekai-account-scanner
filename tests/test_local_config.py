from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from pjsk_scanner.errors import ScannerError
from pjsk_scanner.local_config import load_env_file, parse_env_text, write_private_env


def test_parse_env_values_without_shell_expansion() -> None:
    values = parse_env_text(
        "# local-only settings\n"
        'export ONE="value with spaces" # note\n'
        "TWO='single quoted'\n"
        "THREE=$(touch /tmp/should-not-run)\n"
    )

    assert values == {
        "ONE": "value with spaces",
        "TWO": "single quoted",
        "THREE": "$(touch /tmp/should-not-run)",
    }


def test_parse_env_rejects_malformed_quoted_value() -> None:
    with pytest.raises(ScannerError, match="line 1"):
        parse_env_text('AES_KEY="unfinished')


def test_load_env_preserves_explicit_process_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_text('SEKAI_KR_ACCESS_TOKEN="synthetic-file-token"\n', encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("SEKAI_KR_ACCESS_TOKEN", "synthetic-process-token")

    loaded = load_env_file(path)

    assert loaded["SEKAI_KR_ACCESS_TOKEN"] == "synthetic-file-token"
    assert os.environ["SEKAI_KR_ACCESS_TOKEN"] == "synthetic-process-token"


def test_env_loader_rejects_world_readable_credentials(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text('AES_KEY="synthetic-key"\n', encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(ScannerError, match="chmod 600"):
        load_env_file(path)


def test_private_writer_requires_gitignore_and_sets_restrictive_mode(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    destination = write_private_env(
        {"SEKAI_KR_ACCESS_TOKEN": "synthetic-access-token", "AES_KEY": "synthetic-key"},
        tmp_path / ".env",
    )

    assert destination.read_text(encoding="utf-8").count("=") == 2
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert parse_env_text(destination.read_text(encoding="utf-8")) == {
        "AES_KEY": "synthetic-key",
        "SEKAI_KR_ACCESS_TOKEN": "synthetic-access-token",
    }


def test_private_writer_refuses_unignored_config(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    with pytest.raises(ScannerError, match="Git does not ignore"):
        write_private_env({"AES_KEY": "synthetic-key"}, tmp_path / ".env")
