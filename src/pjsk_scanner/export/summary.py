"""Correctly calculable aggregates for a normalized account."""

from __future__ import annotations

from collections import Counter

from pjsk_scanner.models import NormalizedAccount


def render_summary(account: NormalizedAccount) -> str:
    """Return a concise text report without reading raw suite data."""
    lines: list[str] = ["Project SEKAI account progression"]
    if account.profile is not None:
        profile = account.profile
        if profile.display_name:
            lines.append(f"Player: {profile.display_name}")
        if profile.rank is not None:
            lines.append(f"Rank: {profile.rank}")
        if profile.coins is not None:
            lines.append(f"Coins: {profile.coins}")
        if profile.virtual_currency is not None:
            lines.append(f"Virtual currency: {profile.virtual_currency}")
    if account.charged_currency is not None:
        free_amount = account.charged_currency.free
        paid_amount = account.charged_currency.paid
        lines.append(f"Charged currency: free {free_amount}, paid {paid_amount}")
    lines.append(f"Region: {account.region.upper()}")
    lines.append(f"Generated: {account.generated_at}")
    lines.append("")
    lines.append(f"Cards: {len(account.cards)} owned")
    rarities = Counter(card.rarity or "unknown" for card in account.cards)
    if rarities:
        lines.append(
            "  By rarity: "
            + ", ".join(
                f"{rarity} {count}"
                for rarity, count in sorted(rarities.items(), key=lambda row: row[0])
            )
        )
    trained = sum(card.is_special_trained is True for card in account.cards)
    lines.append(f"  Special trained: {trained}")
    max_master = sum(
        card.master_rank is not None
        and card.max_master_rank is not None
        and card.master_rank >= card.max_master_rank
        for card in account.cards
    )
    max_skill = sum(
        card.skill_level is not None
        and card.max_skill_level is not None
        and card.skill_level >= card.max_skill_level
        for card in account.cards
    )
    lines.append(f"  Max master rank: {max_master}")
    lines.append(f"  Max skill level: {max_skill}")

    lines.append("")
    lines.append(f"Characters: {len(account.characters)} tracked")
    max_character = sum(
        character.character_rank is not None
        and character.max_character_rank is not None
        and character.character_rank >= character.max_character_rank
        for character in account.characters
    )
    lines.append(f"  At current master-data rank cap: {max_character}")

    lines.append("")
    lines.append(f"Materials: {len(account.materials)} types")
    for material in sorted(
        account.materials, key=lambda item: (item.name or "", item.material_id)
    ):
        label = material.name or f"Material {material.material_id}"
        quantity = "unknown" if material.quantity is None else str(material.quantity)
        lines.append(f"  {label}: {quantity}")

    lines.append("")
    lines.append(f"Music results: {len(account.music_results)} records")
    lines.append(
        "  Confirmed clears: "
        f"{sum(result.cleared is True for result in account.music_results)}"
    )
    full_combos = sum(result.full_combo is True for result in account.music_results)
    all_perfects = sum(result.all_perfect is True for result in account.music_results)
    lines.append(f"  Full combos: {full_combos}")
    lines.append(f"  All perfects: {all_perfects}")
    lines.append(f"  Music achievements: {len(account.music_achievements)}")
    lines.append(f"Decks: {len(account.decks)}")
    lines.append(f"Challenge Live stages: {len(account.challenge_live)}")
    lines.append(f"  High-score records: {len(account.challenge_live_scores)}")
    lines.append(f"  High-score rewards: {len(account.challenge_live_rewards)}")
    lines.append(f"  Character decks: {len(account.challenge_live_decks)}")
    if account.unprocessed_suite_fields:
        lines.append("")
        lines.append(
            "Suite fields not normalized: "
            + ", ".join(account.unprocessed_suite_fields)
        )
    return "\n".join(lines)
