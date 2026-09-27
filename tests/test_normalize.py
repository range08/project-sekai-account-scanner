from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pjsk_scanner.errors import SuitePayloadError
from pjsk_scanner.normalize.account import normalize_suite_payload

FIXTURES = Path(__file__).parent / "fixtures"


def suite_fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "suite-user.json").read_text(encoding="utf-8"))


def test_raw_suite_validation_rejects_non_object(master: Any) -> None:
    with pytest.raises(SuitePayloadError, match="must be a JSON object"):
        normalize_suite_payload([], master)


def test_normalizes_cards_and_keeps_missing_optional_fields_none(master: Any) -> None:
    account = normalize_suite_payload(suite_fixture(), master)

    card = account.cards[0]
    assert card.card_id == 1001
    assert card.title == "Synthetic Card"
    assert card.character_name == "Sample Character"
    assert card.rarity == "rarity_4"
    assert card.attribute == "cool"
    assert card.level == 50
    assert card.experience == 7
    assert card.total_experience == 107
    assert card.max_level == 50
    assert card.skill_level == 4
    assert card.skill_experience == 3
    assert card.total_skill_experience == 13
    assert card.max_skill_level == 4
    assert card.master_rank == 5
    assert card.max_master_rank == 5
    assert card.is_special_trained is True
    assert card.power is None
    assert card.episodes[0].episode_id == 5001
    assert card.episodes[0].is_not_skipped is True

    unknown = account.cards[1]
    assert unknown.card_id == 9999
    assert unknown.title is None
    assert unknown.character_name is None
    assert unknown.skill_level is None
    assert unknown.is_special_trained is False


def test_normalizes_character_and_material_lookups(master: Any) -> None:
    account = normalize_suite_payload(suite_fixture(), master)

    character = account.characters[0]
    assert character.name == "Sample Character"
    assert character.unit == "light_sound"
    assert character.voice_actor == "Synthetic Voice"
    assert character.character_rank == 4
    assert character.max_character_rank == 5
    assert account.materials[0].name == "Synthetic Material"
    assert account.materials[0].quantity == 17
    assert account.charged_currency is not None
    assert account.charged_currency.free == 123
    assert account.charged_currency.paid == 45


def test_normalizes_music_without_guessing_result_semantics(master: Any) -> None:
    account = normalize_suite_payload(suite_fixture(), master)

    result = account.music_results[0]
    assert result.title == "Synthetic Song"
    assert result.difficulty == "expert"
    assert result.play_level == 25
    assert result.high_score == 123456
    assert result.full_combo is True
    assert result.all_perfect is False
    assert result.cleared is True
    assert result.result == "synthetic-result"
    assert account.music_results[1].cleared is None
    achievement = account.music_achievements[0]
    assert achievement.music_title == "Synthetic Song"
    assert achievement.achievement_type == "score_rank"
    assert achievement.achievement_value == "RANK_A"


def test_normalizes_decks_challenge_and_unknown_field_names(master: Any) -> None:
    account = normalize_suite_payload(suite_fixture(), master)

    assert account.decks[0].members == [1001, 0, 0, 0, 0]
    assert account.challenge_live[0].character_name == "Sample Character"
    assert account.challenge_live[0].points == 250
    assert account.challenge_live_scores[0].high_score == 100500
    assert account.challenge_live_rewards[0].required_score == 100000
    assert account.challenge_live_rewards[0].status == "received"
    assert account.challenge_live_decks[0].leader == 1001
    assert "userAreas" in account.unprocessed_suite_fields
    assert "userProfile.*.word" in account.unprocessed_suite_fields
    assert "userGamedata.*.userId" in account.unprocessed_suite_fields
    assert "userCards.*.futureCardField" in account.unprocessed_suite_fields
    assert "synthetic-unprocessed-value" not in str(account.to_dict())
    assert "synthetic-future-value" not in str(account.to_dict())
    assert "synthetic private profile text" not in str(account.to_dict())


def test_normalization_requires_card_id_when_a_card_entry_exists(master: Any) -> None:
    payload = {"userCards": [{"level": 1}]}

    with pytest.raises(SuitePayloadError, match=r"userCards\[0\].cardId"):
        normalize_suite_payload(
            payload,
            master,
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
