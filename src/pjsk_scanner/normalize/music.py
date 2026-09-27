"""Normalize song result and difficulty progression."""

from __future__ import annotations

from typing import Any

from pjsk_scanner.master.repository import MasterDataRepository
from pjsk_scanner.models import MusicAchievement, MusicResult
from pjsk_scanner.normalize.fields import bool_field, int_field, rows, str_field


def normalize_music_results(
    payload: dict[str, Any], master: MasterDataRepository
) -> list[MusicResult]:
    results: list[MusicResult] = []
    for index, row in enumerate(rows(payload, "userMusicResults")):
        context = f"userMusicResults[{index}]"
        music_id = int_field(row, "musicId", context, required=True)
        assert music_id is not None
        difficulty = str_field(row, "musicDifficultyType", context)
        music = master.music(music_id)
        difficulty_master = (
            master.music_difficulty(music_id, difficulty)
            if difficulty is not None
            else None
        )
        full_combo = bool_field(row, "fullComboFlg", context)
        all_perfect = bool_field(row, "fullPerfectFlg", context)
        result = str_field(row, "playResult", context)
        results.append(
            MusicResult(
                music_id=music_id,
                title=music.title if music else None,
                difficulty=difficulty,
                play_level=difficulty_master.play_level if difficulty_master else None,
                result=result,
                play_type=str_field(row, "playType", context),
                high_score=int_field(row, "highScore", context),
                cleared=_clear_state(full_combo, all_perfect),
                full_combo=full_combo,
                all_perfect=all_perfect,
                mvp_count=int_field(row, "mvpCount", context),
                superstar_count=int_field(row, "superStarCount", context),
            )
        )
    return results


def normalize_music_achievements(
    payload: dict[str, Any], master: MasterDataRepository
) -> list[MusicAchievement]:
    achievements: list[MusicAchievement] = []
    for index, row in enumerate(rows(payload, "userMusicAchievements")):
        context = f"userMusicAchievements[{index}]"
        music_id = int_field(row, "musicId", context, required=True)
        achievement_id = int_field(row, "musicAchievementId", context, required=True)
        assert music_id is not None and achievement_id is not None
        music = master.music(music_id)
        achievement = master.music_achievement(achievement_id)
        achievements.append(
            MusicAchievement(
                music_id=music_id,
                music_title=music.title if music else None,
                achievement_id=achievement_id,
                achievement_type=(
                    achievement.achievement_type if achievement else None
                ),
                achievement_value=(
                    achievement.achievement_value if achievement else None
                ),
            )
        )
    return achievements


def _clear_state(full_combo: bool | None, all_perfect: bool | None) -> bool | None:
    if full_combo is True or all_perfect is True:
        return True
    return None
