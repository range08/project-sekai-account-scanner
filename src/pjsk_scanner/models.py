"""Typed normalized account domain models.

Dataclasses keep the runtime dependency-free and make the exported schema easy
to inspect. `schema_version` versions the JSON representation independently
from upstream game protocol versions.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, cast


@dataclass(frozen=True)
class AccountProfile:
    display_name: str | None = None
    rank: int | None = None
    experience: int | None = None
    total_experience: int | None = None
    coins: int | None = None
    virtual_currency: int | None = None
    profile_image_id: int | None = None
    profile_image_type: str | None = None


@dataclass(frozen=True)
class ChargedCurrency:
    free: int | None = None
    paid: int | None = None


@dataclass(frozen=True)
class CardEpisodeProgress:
    episode_id: int
    scenario_status: str | None = None
    status_reasons: list[str] = field(default_factory=list)
    is_not_skipped: bool | None = None


@dataclass(frozen=True)
class CardProgress:
    card_id: int
    title: str | None = None
    character_id: int | None = None
    character_name: str | None = None
    rarity: str | None = None
    attribute: str | None = None
    level: int | None = None
    experience: int | None = None
    total_experience: int | None = None
    base_max_level: int | None = None
    training_max_level: int | None = None
    max_level: int | None = None
    skill_level: int | None = None
    skill_experience: int | None = None
    total_skill_experience: int | None = None
    max_skill_level: int | None = None
    skill_name: str | None = None
    skill_description: str | None = None
    master_rank: int | None = None
    max_master_rank: int | None = None
    special_training_status: str | None = None
    is_special_trained: bool | None = None
    default_image: str | None = None
    duplicate_count: int | None = None
    created_at: int | None = None
    episodes: list[CardEpisodeProgress] = field(default_factory=list)
    power: dict[str, int | None] | None = None


@dataclass(frozen=True)
class CharacterProgress:
    character_id: int
    name: str | None = None
    unit: str | None = None
    birthday: str | None = None
    voice_actor: str | None = None
    character_rank: int | None = None
    max_character_rank: int | None = None
    experience: int | None = None
    total_experience: int | None = None


@dataclass(frozen=True)
class MaterialProgress:
    material_id: int
    name: str | None = None
    material_type: str | None = None
    quantity: int | None = None


@dataclass(frozen=True)
class MusicResult:
    music_id: int
    title: str | None = None
    difficulty: str | None = None
    play_level: int | None = None
    result: str | None = None
    play_type: str | None = None
    high_score: int | None = None
    cleared: bool | None = None
    full_combo: bool | None = None
    all_perfect: bool | None = None
    mvp_count: int | None = None
    superstar_count: int | None = None


@dataclass(frozen=True)
class MusicAchievement:
    music_id: int
    music_title: str | None = None
    achievement_id: int | None = None
    achievement_type: str | None = None
    achievement_value: str | None = None


@dataclass(frozen=True)
class DeckProgress:
    deck_id: int
    name: str | None = None
    leader: int | None = None
    sub_leader: int | None = None
    members: list[int | None] = field(default_factory=list)


@dataclass(frozen=True)
class ChallengeLiveStage:
    character_id: int
    character_name: str | None = None
    stage_type: str | None = None
    stage_id: int | None = None
    rank: int | None = None
    status: str | None = None
    points: int | None = None


@dataclass(frozen=True)
class ChallengeLiveScore:
    character_id: int
    character_name: str | None = None
    high_score: int | None = None


@dataclass(frozen=True)
class ChallengeLiveReward:
    character_id: int
    character_name: str | None = None
    reward_id: int | None = None
    required_score: int | None = None
    status: str | None = None


@dataclass(frozen=True)
class ChallengeLiveDeck:
    character_id: int
    character_name: str | None = None
    leader: int | None = None
    supports: list[int | None] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizedAccount:
    schema_version: int
    region: str
    generated_at: str
    profile: AccountProfile | None = None
    charged_currency: ChargedCurrency | None = None
    cards: list[CardProgress] = field(default_factory=list)
    characters: list[CharacterProgress] = field(default_factory=list)
    materials: list[MaterialProgress] = field(default_factory=list)
    music_results: list[MusicResult] = field(default_factory=list)
    music_achievements: list[MusicAchievement] = field(default_factory=list)
    decks: list[DeckProgress] = field(default_factory=list)
    challenge_live: list[ChallengeLiveStage] = field(default_factory=list)
    challenge_live_scores: list[ChallengeLiveScore] = field(default_factory=list)
    challenge_live_rewards: list[ChallengeLiveReward] = field(default_factory=list)
    challenge_live_decks: list[ChallengeLiveDeck] = field(default_factory=list)
    unprocessed_suite_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the stable JSON representation of this account."""
        return cast(dict[str, Any], _camel_case(asdict(self)))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> NormalizedAccount:
        """Build a normalized account from its exported JSON representation."""
        try:
            if value.get("schemaVersion") != 1:
                raise ValueError("unsupported normalized schemaVersion")
            profile_value = value.get("profile")
            currency_value = value.get("chargedCurrency")
            unprocessed = value.get("unprocessedSuiteFields", [])
            if profile_value is not None and not isinstance(profile_value, dict):
                raise TypeError("profile must be an object or null")
            if currency_value is not None and not isinstance(currency_value, dict):
                raise TypeError("chargedCurrency must be an object or null")
            if not isinstance(unprocessed, list) or not all(
                isinstance(item, str) for item in unprocessed
            ):
                raise TypeError("unprocessedSuiteFields must be an array of strings")
            return cls(
                schema_version=1,
                region=str(value["region"]),
                generated_at=str(value["generatedAt"]),
                profile=(
                    _profile_from_dict(profile_value)
                    if isinstance(profile_value, dict)
                    else None
                ),
                charged_currency=(
                    _currency_from_dict(currency_value)
                    if isinstance(currency_value, dict)
                    else None
                ),
                cards=[_card_from_dict(item) for item in _dict_list(value, "cards")],
                characters=[
                    _character_from_dict(item)
                    for item in _dict_list(value, "characters")
                ],
                materials=[
                    _material_from_dict(item) for item in _dict_list(value, "materials")
                ],
                music_results=[
                    _music_from_dict(item) for item in _dict_list(value, "musicResults")
                ],
                music_achievements=[
                    _achievement_from_dict(item)
                    for item in _dict_list(value, "musicAchievements")
                ],
                decks=[_deck_from_dict(item) for item in _dict_list(value, "decks")],
                challenge_live=[
                    _challenge_from_dict(item)
                    for item in _dict_list(value, "challengeLive")
                ],
                challenge_live_scores=[
                    _challenge_score_from_dict(item)
                    for item in _dict_list(value, "challengeLiveScores")
                ],
                challenge_live_rewards=[
                    _challenge_reward_from_dict(item)
                    for item in _dict_list(value, "challengeLiveRewards")
                ],
                challenge_live_decks=[
                    _challenge_deck_from_dict(item)
                    for item in _dict_list(value, "challengeLiveDecks")
                ],
                unprocessed_suite_fields=unprocessed,
            )
        except (KeyError, TypeError) as error:
            raise ValueError("invalid normalized account JSON") from error


def _camel_case(value: Any) -> Any:
    if isinstance(value, dict):
        return {_to_camel(key): _camel_case(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_camel_case(item) for item in value]
    return value


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


def _snake_case_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {_to_snake(key): item for key, item in value.items()}


def _to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _dict_list(value: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = value.get(key, [])
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise TypeError(f"{key} must be an array of objects")
    return items


def _profile_from_dict(value: dict[str, Any]) -> AccountProfile:
    return AccountProfile(**_snake_case_mapping(value))


def _currency_from_dict(value: dict[str, Any]) -> ChargedCurrency:
    return ChargedCurrency(**_snake_case_mapping(value))


def _card_from_dict(value: dict[str, Any]) -> CardProgress:
    normalized = _snake_case_mapping(value)
    normalized["episodes"] = [
        CardEpisodeProgress(**_snake_case_mapping(item))
        for item in _dict_list(normalized, "episodes")
    ]
    return CardProgress(**normalized)


def _character_from_dict(value: dict[str, Any]) -> CharacterProgress:
    return CharacterProgress(**_snake_case_mapping(value))


def _material_from_dict(value: dict[str, Any]) -> MaterialProgress:
    return MaterialProgress(**_snake_case_mapping(value))


def _music_from_dict(value: dict[str, Any]) -> MusicResult:
    return MusicResult(**_snake_case_mapping(value))


def _achievement_from_dict(value: dict[str, Any]) -> MusicAchievement:
    return MusicAchievement(**_snake_case_mapping(value))


def _deck_from_dict(value: dict[str, Any]) -> DeckProgress:
    return DeckProgress(**_snake_case_mapping(value))


def _challenge_from_dict(value: dict[str, Any]) -> ChallengeLiveStage:
    return ChallengeLiveStage(**_snake_case_mapping(value))


def _challenge_score_from_dict(value: dict[str, Any]) -> ChallengeLiveScore:
    return ChallengeLiveScore(**_snake_case_mapping(value))


def _challenge_reward_from_dict(value: dict[str, Any]) -> ChallengeLiveReward:
    return ChallengeLiveReward(**_snake_case_mapping(value))


def _challenge_deck_from_dict(value: dict[str, Any]) -> ChallengeLiveDeck:
    return ChallengeLiveDeck(**_snake_case_mapping(value))
