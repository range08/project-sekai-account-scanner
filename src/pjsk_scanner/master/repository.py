"""Validated, indexed queries over cached master-data tables."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pjsk_scanner.errors import MasterDataError
from pjsk_scanner.master.models import (
    CardMaster,
    ChallengeLiveRewardMaster,
    CharacterMaster,
    CharacterProfileMaster,
    MaterialMaster,
    MusicAchievementMaster,
    MusicDifficultyMaster,
    MusicMaster,
    RarityMaster,
    SkillMaster,
)


class MasterDataRepository:
    """Load required tables once and expose ID-based lookups to normalizers."""

    def __init__(self, master_dir: str | Path, region: str = "kr") -> None:
        self.master_dir = Path(master_dir) / region
        self.region = region
        tables = {
            name: self._load_table(name)
            for name in (
                "cards",
                "cardRarities",
                "gameCharacters",
                "characterProfiles",
                "characterRanks",
                "materials",
                "musics",
                "musicDifficulties",
                "skills",
                "masterLessons",
                "musicAchievements",
                "challengeLiveHighScoreRewards",
            )
        }
        self._cards = _index(tables["cards"], "id")
        self._rarities = _index(tables["cardRarities"], "cardRarityType")
        self._characters = _index(tables["gameCharacters"], "id")
        self._character_profiles = _index(tables["characterProfiles"], "characterId")
        self._materials = _index(tables["materials"], "id")
        self._musics = _index(tables["musics"], "id")
        self._skills = _index(tables["skills"], "id")
        self._music_achievements = _index(tables["musicAchievements"], "id")
        self._challenge_live_rewards = _index(
            tables["challengeLiveHighScoreRewards"], "id"
        )
        self._music_difficulties = {
            (row.get("musicId"), row.get("musicDifficulty")): row
            for row in tables["musicDifficulties"]
        }
        self._max_character_rank: dict[int, int] = defaultdict(int)
        for row in tables["characterRanks"]:
            character_id = _int(row.get("characterId"))
            rank = _int(row.get("characterRank"))
            if character_id is not None and rank is not None:
                self._max_character_rank[character_id] = max(
                    self._max_character_rank[character_id], rank
                )
        self._max_master_rank: dict[str, int] = defaultdict(int)
        for row in tables["masterLessons"]:
            rarity = row.get("cardRarityType")
            rank = _int(row.get("masterRank"))
            if isinstance(rarity, str) and rank is not None:
                self._max_master_rank[rarity] = max(self._max_master_rank[rarity], rank)

    def card(self, card_id: int) -> CardMaster | None:
        row = self._cards.get(card_id)
        if row is None:
            return None
        return CardMaster(
            card_id=card_id,
            title=_str(row.get("prefix")),
            character_id=_int(row.get("characterId")),
            rarity=_str(row.get("cardRarityType")),
            attribute=_str(row.get("attr")),
            skill_id=_int(row.get("skillId")),
            skill_name=_str(row.get("cardSkillName")),
        )

    def rarity(self, rarity: str | None) -> RarityMaster | None:
        if rarity is None:
            return None
        row = self._rarities.get(rarity)
        if row is None:
            return None
        return RarityMaster(
            rarity=rarity,
            max_level=_int(row.get("maxLevel")),
            training_max_level=_int(row.get("trainingMaxLevel")),
            max_skill_level=_int(row.get("maxSkillLevel")),
        )

    def character(self, character_id: int) -> CharacterMaster | None:
        row = self._characters.get(character_id)
        if row is None:
            return None
        first_name = _str(row.get("firstName")) or ""
        given_name = _str(row.get("givenName")) or ""
        display_name = f"{first_name}{given_name}".strip() or None
        return CharacterMaster(
            character_id=character_id,
            name=display_name,
            unit=_str(row.get("unit")),
        )

    def character_profile(self, character_id: int) -> CharacterProfileMaster | None:
        row = self._character_profiles.get(character_id)
        if row is None:
            return None
        return CharacterProfileMaster(
            character_id=character_id,
            birthday=_str(row.get("birthday")),
            voice_actor=_str(row.get("characterVoice")),
        )

    def max_character_rank(self, character_id: int) -> int | None:
        return self._max_character_rank.get(character_id) or None

    def material(self, material_id: int) -> MaterialMaster | None:
        row = self._materials.get(material_id)
        if row is None:
            return None
        return MaterialMaster(
            material_id=material_id,
            name=_str(row.get("name")),
            material_type=_str(row.get("materialType")),
        )

    def music(self, music_id: int) -> MusicMaster | None:
        row = self._musics.get(music_id)
        if row is None:
            return None
        return MusicMaster(music_id=music_id, title=_str(row.get("title")))

    def music_difficulty(
        self, music_id: int, difficulty: str
    ) -> MusicDifficultyMaster | None:
        row = self._music_difficulties.get((music_id, difficulty))
        if row is None:
            return None
        return MusicDifficultyMaster(
            music_id=music_id,
            difficulty=difficulty,
            play_level=_int(row.get("playLevel")),
        )

    def max_master_rank(self, rarity: str | None) -> int | None:
        if rarity is None:
            return None
        return self._max_master_rank.get(rarity) or None

    def skill(self, skill_id: int | None) -> SkillMaster | None:
        if skill_id is None:
            return None
        row = self._skills.get(skill_id)
        if row is None:
            return None
        return SkillMaster(skill_id=skill_id, description=_str(row.get("description")))

    def music_achievement(self, achievement_id: int) -> MusicAchievementMaster | None:
        row = self._music_achievements.get(achievement_id)
        if row is None:
            return None
        return MusicAchievementMaster(
            achievement_id=achievement_id,
            achievement_type=_str(row.get("musicAchievementType")),
            achievement_value=_str(row.get("musicAchievementTypeValue")),
        )

    def challenge_live_reward(self, reward_id: int) -> ChallengeLiveRewardMaster | None:
        row = self._challenge_live_rewards.get(reward_id)
        if row is None:
            return None
        return ChallengeLiveRewardMaster(
            reward_id=reward_id,
            character_id=_int(row.get("characterId")),
            required_score=_int(row.get("highScore")),
        )

    def _load_table(self, name: str) -> list[dict[str, Any]]:
        path = self.master_dir / f"{name}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise MasterDataError(f"Missing master-data table: {path.name}") from None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise MasterDataError(f"Malformed master-data JSON: {path.name}") from None
        if not isinstance(value, list) or not all(
            isinstance(row, dict) for row in value
        ):
            raise MasterDataError(f"Master-data table {path.name} must be an array")
        return value


def _index(rows: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    indexed: dict[Any, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if value is not None:
            indexed[value] = row
    return indexed


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None
