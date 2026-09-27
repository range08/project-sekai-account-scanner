"""Small typed views over the master-data tables used during normalization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CardMaster:
    card_id: int
    title: str | None
    character_id: int | None
    rarity: str | None
    attribute: str | None
    skill_id: int | None
    skill_name: str | None


@dataclass(frozen=True)
class RarityMaster:
    rarity: str
    max_level: int | None
    max_skill_level: int | None


@dataclass(frozen=True)
class CharacterMaster:
    character_id: int
    name: str | None
    unit: str | None


@dataclass(frozen=True)
class CharacterProfileMaster:
    character_id: int
    birthday: str | None
    voice_actor: str | None


@dataclass(frozen=True)
class MaterialMaster:
    material_id: int
    name: str | None
    material_type: str | None


@dataclass(frozen=True)
class MusicMaster:
    music_id: int
    title: str | None


@dataclass(frozen=True)
class MusicDifficultyMaster:
    music_id: int
    difficulty: str
    play_level: int | None


@dataclass(frozen=True)
class SkillMaster:
    skill_id: int
    description: str | None


@dataclass(frozen=True)
class MusicAchievementMaster:
    achievement_id: int
    achievement_type: str | None
    achievement_value: str | None


@dataclass(frozen=True)
class ChallengeLiveRewardMaster:
    reward_id: int
    character_id: int | None
    required_score: int | None
