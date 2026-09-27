from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pjsk_scanner.master.repository import MasterDataRepository

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def master_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "master"
    shutil.copytree(FIXTURES / "master", destination)
    return destination


@pytest.fixture
def master(master_dir: Path) -> MasterDataRepository:
    return MasterDataRepository(master_dir)
