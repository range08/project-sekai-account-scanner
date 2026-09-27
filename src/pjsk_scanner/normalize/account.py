"""Validate a suite response and normalize supported account progression."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pjsk_scanner.errors import SuitePayloadError
from pjsk_scanner.master.repository import MasterDataRepository
from pjsk_scanner.models import AccountProfile, ChargedCurrency, NormalizedAccount
from pjsk_scanner.normalize.cards import normalize_cards
from pjsk_scanner.normalize.challenge import (
    normalize_challenge_live,
    normalize_challenge_live_decks,
    normalize_challenge_live_rewards,
    normalize_challenge_live_scores,
)
from pjsk_scanner.normalize.characters import normalize_characters
from pjsk_scanner.normalize.decks import normalize_decks
from pjsk_scanner.normalize.fields import int_field, object_field, str_field
from pjsk_scanner.normalize.materials import normalize_materials
from pjsk_scanner.normalize.music import (
    normalize_music_achievements,
    normalize_music_results,
)

_PROCESSED_FIELDS = {
    "userGamedata",
    "userProfile",
    "userChargedCurrency",
    "userCards",
    "userCharacters",
    "userMaterials",
    "userMusicResults",
    "userMusicAchievements",
    "userDecks",
    "userChallengeLiveSoloStages",
    "userChallengeLiveSoloResults",
    "userChallengeLiveSoloHighScoreRewards",
    "userChallengeLiveSoloDecks",
}
_OBJECT_FIELDS = {"userGamedata", "userProfile", "userChargedCurrency"}
_SOURCE_FIELDS = {
    "userGamedata": {
        "coin",
        "customProfileId",
        "deck",
        "exp",
        "lastLoginAt",
        "name",
        "rank",
        "totalExp",
        "userId",
        "virtualCoin",
    },
    "userProfile": {"profileImageId", "profileImageType", "twitterId", "word"},
    "userChargedCurrency": {"free", "paid", "paidUnitPrices"},
    "userCards": {
        "cardId",
        "level",
        "exp",
        "totalExp",
        "skillLevel",
        "skillExp",
        "totalSkillExp",
        "masterRank",
        "specialTrainingStatus",
        "defaultImage",
        "duplicateCount",
        "createdAt",
        "episodes",
    },
    "userCharacters": {"characterId", "characterRank", "exp", "totalExp", "userId"},
    "userMaterials": {"materialId", "quantity"},
    "userMusicResults": {
        "fullComboFlg",
        "fullPerfectFlg",
        "highScore",
        "musicDifficultyType",
        "musicId",
        "mvpCount",
        "playResult",
        "playType",
        "superStarCount",
    },
    "userMusicAchievements": {"musicAchievementId", "musicId"},
    "userDecks": {
        "deckId",
        "leader",
        "member1",
        "member2",
        "member3",
        "member4",
        "member5",
        "name",
        "subLeader",
        "userId",
    },
    "userChallengeLiveSoloStages": {
        "challengeLiveStageType",
        "characterId",
        "challengeLiveStageId",
        "rank",
        "challengeLiveStageStatus",
        "point",
    },
    "userChallengeLiveSoloResults": {"characterId", "highScore"},
    "userChallengeLiveSoloHighScoreRewards": {
        "characterId",
        "challengeLiveHighScoreRewardId",
        "challengeLiveHighScoreStatus",
    },
    "userChallengeLiveSoloDecks": {
        "characterId",
        "leader",
        "support1",
        "support2",
        "support3",
        "support4",
    },
}
_OMITTED_FIELDS = {
    "userGamedata": {"customProfileId", "deck", "lastLoginAt", "userId"},
    "userProfile": {"twitterId", "word"},
    "userChargedCurrency": {"paidUnitPrices"},
}
_CARD_EPISODE_FIELDS = {
    "cardEpisodeId",
    "scenarioStatus",
    "scenarioStatusReasons",
    "isNotSkipped",
}


def normalize_suite_payload(
    payload: object,
    master: MasterDataRepository,
    *,
    region: str = "kr",
    generated_at: datetime | None = None,
) -> NormalizedAccount:
    """Validate the top-level suite response and map known domains to models."""
    if not isinstance(payload, dict):
        raise SuitePayloadError("Suite user payload must be a JSON object")
    for field in _PROCESSED_FIELDS:
        if field in payload and payload[field] is not None:
            if field in _OBJECT_FIELDS and not isinstance(payload[field], dict):
                raise SuitePayloadError(f"Suite field {field} must be an object")
            if field not in _OBJECT_FIELDS and not isinstance(payload[field], list):
                raise SuitePayloadError(f"Suite field {field} must be an array")
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    generated_string = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    present_unprocessed = _unprocessed_fields(payload)
    return NormalizedAccount(
        schema_version=1,
        region=region,
        generated_at=generated_string,
        profile=_normalize_profile(payload),
        charged_currency=_normalize_charged_currency(payload),
        cards=normalize_cards(payload, master),
        characters=normalize_characters(payload, master),
        materials=normalize_materials(payload, master),
        music_results=normalize_music_results(payload, master),
        music_achievements=normalize_music_achievements(payload, master),
        decks=normalize_decks(payload),
        challenge_live=normalize_challenge_live(payload, master),
        challenge_live_scores=normalize_challenge_live_scores(payload, master),
        challenge_live_rewards=normalize_challenge_live_rewards(payload, master),
        challenge_live_decks=normalize_challenge_live_decks(payload, master),
        unprocessed_suite_fields=present_unprocessed,
    )


def _normalize_profile(payload: dict[str, Any]) -> AccountProfile | None:
    gamedata = object_field(payload, "userGamedata")
    profile = object_field(payload, "userProfile")
    if gamedata is None and profile is None:
        return None
    game = gamedata or {}
    public_profile = profile or {}
    return AccountProfile(
        display_name=str_field(game, "name", "userGamedata"),
        rank=int_field(game, "rank", "userGamedata"),
        experience=int_field(game, "exp", "userGamedata"),
        total_experience=int_field(game, "totalExp", "userGamedata"),
        coins=int_field(game, "coin", "userGamedata"),
        virtual_currency=int_field(game, "virtualCoin", "userGamedata"),
        profile_image_id=int_field(public_profile, "profileImageId", "userProfile"),
        profile_image_type=str_field(public_profile, "profileImageType", "userProfile"),
    )


def _normalize_charged_currency(
    payload: dict[str, Any],
) -> ChargedCurrency | None:
    currency = object_field(payload, "userChargedCurrency")
    if currency is None:
        return None
    return ChargedCurrency(
        free=int_field(currency, "free", "userChargedCurrency"),
        paid=int_field(currency, "paid", "userChargedCurrency"),
    )


def _unprocessed_fields(payload: dict[str, Any]) -> list[str]:
    names = {
        key
        for key, value in payload.items()
        if key not in _PROCESSED_FIELDS and value not in (None, [], {})
    }
    for field, known_fields in _SOURCE_FIELDS.items():
        value = payload.get(field)
        if value is None:
            continue
        entries = [value] if isinstance(value, dict) else value
        if not isinstance(entries, list):
            continue
        omitted_fields = _OMITTED_FIELDS.get(field, set())
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for nested_field in entry:
                if nested_field not in known_fields or nested_field in omitted_fields:
                    names.add(f"{field}.*.{nested_field}")
            if field == "userCards":
                _add_unprocessed_episode_fields(entry, names)
    return sorted(names)


def _add_unprocessed_episode_fields(card: dict[str, Any], names: set[str]) -> None:
    episodes = card.get("episodes")
    if not isinstance(episodes, list):
        return
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        for field in episode:
            if field not in _CARD_EPISODE_FIELDS:
                names.add(f"userCards.*.episodes.*.{field}")
