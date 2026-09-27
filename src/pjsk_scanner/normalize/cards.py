"""Normalize owned cards and enrich them from the regional master data."""

from __future__ import annotations

from typing import Any

from pjsk_scanner.errors import SuitePayloadError
from pjsk_scanner.master.repository import MasterDataRepository
from pjsk_scanner.models import CardEpisodeProgress, CardProgress
from pjsk_scanner.normalize.fields import (
    bool_field,
    int_field,
    rows,
    str_field,
)


def normalize_cards(
    payload: dict[str, Any], master: MasterDataRepository
) -> list[CardProgress]:
    cards: list[CardProgress] = []
    for index, row in enumerate(rows(payload, "userCards")):
        context = f"userCards[{index}]"
        card_id = int_field(row, "cardId", context, required=True)
        assert card_id is not None
        card_master = master.card(card_id)
        rarity = master.rarity(card_master.rarity if card_master else None)
        character = (
            master.character(card_master.character_id)
            if card_master and card_master.character_id is not None
            else None
        )
        skill = master.skill(card_master.skill_id if card_master else None)
        training_status = str_field(row, "specialTrainingStatus", context)
        cards.append(
            CardProgress(
                card_id=card_id,
                title=card_master.title if card_master else None,
                character_id=card_master.character_id if card_master else None,
                character_name=character.name if character else None,
                rarity=card_master.rarity if card_master else None,
                attribute=card_master.attribute if card_master else None,
                level=int_field(row, "level", context),
                experience=int_field(row, "exp", context),
                total_experience=int_field(row, "totalExp", context),
                max_level=rarity.max_level if rarity else None,
                skill_level=int_field(row, "skillLevel", context),
                skill_experience=int_field(row, "skillExp", context),
                total_skill_experience=int_field(row, "totalSkillExp", context),
                max_skill_level=rarity.max_skill_level if rarity else None,
                skill_name=card_master.skill_name if card_master else None,
                skill_description=skill.description if skill else None,
                master_rank=int_field(row, "masterRank", context),
                max_master_rank=(
                    master.max_master_rank(card_master.rarity) if card_master else None
                ),
                special_training_status=training_status,
                is_special_trained=_training_complete(training_status),
                default_image=str_field(row, "defaultImage", context),
                duplicate_count=int_field(row, "duplicateCount", context),
                created_at=int_field(row, "createdAt", context),
                episodes=_normalize_episodes(row, context),
                power=None,
            )
        )
    return cards


def _normalize_episodes(
    card_row: dict[str, Any], context: str
) -> list[CardEpisodeProgress]:
    value = card_row.get("episodes", [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SuitePayloadError(f"{context}.episodes must be an array of objects")
    episodes: list[CardEpisodeProgress] = []
    for index, row in enumerate(value):
        episode_context = f"{context}.episodes[{index}]"
        episode_id = int_field(row, "cardEpisodeId", episode_context, required=True)
        reasons = row.get("scenarioStatusReasons", [])
        if not isinstance(reasons, list) or not all(
            isinstance(reason, str) for reason in reasons
        ):
            raise SuitePayloadError(
                f"{episode_context}.scenarioStatusReasons must be an array of strings"
            )
        assert episode_id is not None
        episodes.append(
            CardEpisodeProgress(
                episode_id=episode_id,
                scenario_status=str_field(row, "scenarioStatus", episode_context),
                status_reasons=reasons,
                is_not_skipped=bool_field(row, "isNotSkipped", episode_context),
            )
        )
    return episodes


def _training_complete(status: str | None) -> bool | None:
    if status == "done":
        return True
    if status == "not_doing":
        return False
    return None
