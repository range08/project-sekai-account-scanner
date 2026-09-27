"""Conditional, validated downloads for region master-data JSON files."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pjsk_scanner.errors import MasterDataError

MASTER_FILES = (
    "cards.json",
    "cardRarities.json",
    "gameCharacters.json",
    "characterProfiles.json",
    "characterRanks.json",
    "materials.json",
    "musics.json",
    "musicDifficulties.json",
    "skills.json",
    "masterLessons.json",
    "musicAchievements.json",
    "challengeLiveHighScoreRewards.json",
)

REGION_SOURCES = {
    "kr": "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-kr-diff/main",
}


class MasterDataDownloader:
    """Download only scanner-relevant tables, caching ETag/Last-Modified values."""

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        timeout_seconds: float = 30.0,
        base_url: str | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds
        self.base_url = (base_url or "").rstrip("/")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def sync(self, region: str) -> list[Path]:
        """Download each required table for a supported region."""
        if region not in REGION_SOURCES:
            raise MasterDataError(f"Unsupported master-data region: {region}")
        base_url = self.base_url or REGION_SOURCES[region]
        region_dir = self.cache_dir / region
        region_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for filename in MASTER_FILES:
            destination = region_dir / filename
            self._sync_file(f"{base_url}/{filename}", destination)
            written.append(destination)
        return written

    def _sync_file(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        headers = {"User-Agent": "pjsk-account-scanner/0.1"}
        valid_cache = self._is_valid_cache(destination)
        metadata_path = destination.with_suffix(destination.suffix + ".http.json")
        metadata = self._read_metadata(metadata_path) if valid_cache else {}
        for metadata_key, header_name in (
            ("etag", "If-None-Match"),
            ("last_modified", "If-Modified-Since"),
        ):
            header_value = metadata.get(metadata_key)
            if isinstance(header_value, str) and header_value:
                headers[header_name] = header_value
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                content = response.read()
                parsed = self._parse_table(content, destination.name)
                del parsed
                self._atomic_write(destination, content)
                self._atomic_write_json(
                    metadata_path,
                    {
                        "etag": response.headers.get("ETag"),
                        "last_modified": response.headers.get("Last-Modified"),
                    },
                )
        except urllib.error.HTTPError as error:
            if error.code == 304 and valid_cache:
                return
            raise MasterDataError(
                f"Master-data download failed for {destination.name} "
                f"(HTTP {error.code})"
            ) from None
        except urllib.error.URLError as error:
            reason_type = type(error.reason).__name__
            raise MasterDataError(
                f"Master-data download failed for {destination.name} ({reason_type})"
            ) from None
        except TimeoutError:
            raise MasterDataError(
                f"Master-data download timed out for {destination.name}"
            ) from None

    @staticmethod
    def _is_valid_cache(path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            MasterDataDownloader._parse_table(path.read_bytes(), path.name)
        except (OSError, MasterDataError):
            return False
        return True

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _parse_table(content: bytes, filename: str) -> list[dict[str, Any]]:
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MasterDataError(f"Malformed master JSON in {filename}") from error
        if not isinstance(value, list) or not all(
            isinstance(row, dict) for row in value
        ):
            raise MasterDataError(
                f"Master table {filename} must contain a JSON array of objects"
            )
        return value

    @staticmethod
    def _atomic_write(destination: Path, content: bytes) -> None:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _atomic_write_json(cls, destination: Path, value: dict[str, Any]) -> None:
        cls._atomic_write(
            destination,
            json.dumps(value, ensure_ascii=True, indent=2).encode("utf-8"),
        )
