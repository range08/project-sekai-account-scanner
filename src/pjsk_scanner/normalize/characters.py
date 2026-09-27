"""Normalize character rank and experience progression."""

from __future__ import annotations

from typing import Any

from pjsk_scanner.master.repository import MasterDataRepository
from pjsk_scanner.models import CharacterProgress
from pjsk_scanner.normalize.fields import int_field, rows


def normalize_characters(
    payload: dict[str, Any], master: MasterDataRepository
) -> list[CharacterProgress]:
    characters: list[CharacterProgress] = []
    for index, row in enumerate(rows(payload, "userCharacters")):
        context = f"userCharacters[{index}]"
        character_id = int_field(row, "characterId", context, required=True)
        assert character_id is not None
        character = master.character(character_id)
        profile = master.character_profile(character_id)
        characters.append(
            CharacterProgress(
                character_id=character_id,
                name=character.name if character else None,
                unit=character.unit if character else None,
                birthday=profile.birthday if profile else None,
                voice_actor=profile.voice_actor if profile else None,
                character_rank=int_field(row, "characterRank", context),
                max_character_rank=master.max_character_rank(character_id),
                experience=int_field(row, "exp", context),
                total_experience=int_field(row, "totalExp", context),
            )
        )
    return characters
