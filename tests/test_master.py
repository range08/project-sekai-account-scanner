from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from pjsk_scanner.errors import MasterDataError
from pjsk_scanner.master.downloader import MasterDataDownloader
from pjsk_scanner.master.repository import MasterDataRepository


def test_master_repository_loads_and_indexes_tables(master_dir: Path) -> None:
    repository = MasterDataRepository(master_dir)

    card = repository.card(1001)
    character = repository.character(1)
    material = repository.material(3001)
    difficulty = repository.music_difficulty(4001, "expert")
    assert card is not None and card.title == "Synthetic Card"
    assert character is not None and character.name == "Sample Character"
    assert material is not None and material.name == "Synthetic Material"
    assert difficulty is not None and difficulty.play_level == 25
    rarity = repository.rarity("rarity_4")
    assert rarity is not None and rarity.training_max_level == 60
    assert repository.max_master_rank("rarity_4") == 5
    assert repository.max_character_rank(1) == 5


def test_repository_rejects_malformed_master_json(master_dir: Path) -> None:
    (master_dir / "kr" / "cards.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(MasterDataError, match="Malformed master-data JSON: cards.json"):
        MasterDataRepository(master_dir)


def test_downloader_uses_cached_etag_for_unchanged_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests_seen: list[dict[str, str]] = []
    body = json.dumps([]).encode()

    class FakeResponse:
        headers = {
            "ETag": '"version-1"',
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
        }

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return body

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        del timeout
        headers = request.headers
        requests_seen.append(dict(headers))
        if len(requests_seen) == 1:
            return FakeResponse()
        raise HTTPError(
            "https://example.invalid/cards.json", 304, "Not Modified", {}, None
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    downloader = MasterDataDownloader(
        tmp_path / "cache", base_url="https://example.invalid"
    )
    destination = tmp_path / "cache" / "kr" / "cards.json"
    downloader._sync_file("https://example.invalid/cards.json", destination)
    downloader._sync_file("https://example.invalid/cards.json", destination)

    assert destination.read_bytes() == body
    assert requests_seen[1]["If-none-match"] == '"version-1"'
