"""Normalize challenge-live solo stage progression."""

from __future__ import annotations

from typing import Any

from pjsk_scanner.master.repository import MasterDataRepository
from pjsk_scanner.models import (
    ChallengeLiveDeck,
    ChallengeLiveReward,
    ChallengeLiveScore,
    ChallengeLiveStage,
)
from pjsk_scanner.normalize.fields import int_field, rows, str_field


def normalize_challenge_live(
    payload: dict[str, Any], master: MasterDataRepository
) -> list[ChallengeLiveStage]:
    stages: list[ChallengeLiveStage] = []
    for index, row in enumerate(rows(payload, "userChallengeLiveSoloStages")):
        context = f"userChallengeLiveSoloStages[{index}]"
        character_id = int_field(row, "characterId", context, required=True)
        assert character_id is not None
        character = master.character(character_id)
        stages.append(
            ChallengeLiveStage(
                character_id=character_id,
                character_name=character.name if character else None,
                stage_type=str_field(row, "challengeLiveStageType", context),
                stage_id=int_field(row, "challengeLiveStageId", context),
                rank=int_field(row, "rank", context),
                status=str_field(row, "challengeLiveStageStatus", context),
                points=int_field(row, "point", context),
            )
        )
    return stages


def normalize_challenge_live_scores(
    payload: dict[str, Any], master: MasterDataRepository
) -> list[ChallengeLiveScore]:
    scores: list[ChallengeLiveScore] = []
    for index, row in enumerate(rows(payload, "userChallengeLiveSoloResults")):
        context = f"userChallengeLiveSoloResults[{index}]"
        character_id = int_field(row, "characterId", context, required=True)
        assert character_id is not None
        character = master.character(character_id)
        scores.append(
            ChallengeLiveScore(
                character_id=character_id,
                character_name=character.name if character else None,
                high_score=int_field(row, "highScore", context),
            )
        )
    return scores


def normalize_challenge_live_rewards(
    payload: dict[str, Any], master: MasterDataRepository
) -> list[ChallengeLiveReward]:
    rewards: list[ChallengeLiveReward] = []
    for index, row in enumerate(rows(payload, "userChallengeLiveSoloHighScoreRewards")):
        context = f"userChallengeLiveSoloHighScoreRewards[{index}]"
        character_id = int_field(row, "characterId", context, required=True)
        reward_id = int_field(
            row, "challengeLiveHighScoreRewardId", context, required=True
        )
        assert character_id is not None and reward_id is not None
        character = master.character(character_id)
        reward = master.challenge_live_reward(reward_id)
        required_score = (
            reward.required_score
            if reward is not None and reward.character_id in (None, character_id)
            else None
        )
        rewards.append(
            ChallengeLiveReward(
                character_id=character_id,
                character_name=character.name if character else None,
                reward_id=reward_id,
                required_score=required_score,
                status=str_field(row, "challengeLiveHighScoreStatus", context),
            )
        )
    return rewards


def normalize_challenge_live_decks(
    payload: dict[str, Any], master: MasterDataRepository
) -> list[ChallengeLiveDeck]:
    decks: list[ChallengeLiveDeck] = []
    for index, row in enumerate(rows(payload, "userChallengeLiveSoloDecks")):
        context = f"userChallengeLiveSoloDecks[{index}]"
        character_id = int_field(row, "characterId", context, required=True)
        assert character_id is not None
        character = master.character(character_id)
        decks.append(
            ChallengeLiveDeck(
                character_id=character_id,
                character_name=character.name if character else None,
                leader=int_field(row, "leader", context),
                supports=[
                    int_field(row, f"support{slot}", context) for slot in range(1, 5)
                ],
            )
        )
    return decks
