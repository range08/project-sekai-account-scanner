"""Normalize player decks without guessing what source slot IDs reference."""

from __future__ import annotations

from typing import Any

from pjsk_scanner.models import DeckProgress
from pjsk_scanner.normalize.fields import int_field, rows, str_field


def normalize_decks(payload: dict[str, Any]) -> list[DeckProgress]:
    decks: list[DeckProgress] = []
    for index, row in enumerate(rows(payload, "userDecks")):
        context = f"userDecks[{index}]"
        deck_id = int_field(row, "deckId", context, required=True)
        assert deck_id is not None
        members = [int_field(row, f"member{slot}", context) for slot in range(1, 6)]
        decks.append(
            DeckProgress(
                deck_id=deck_id,
                name=str_field(row, "name", context),
                leader=int_field(row, "leader", context),
                sub_leader=int_field(row, "subLeader", context),
                members=members,
            )
        )
    return decks
