"""Obviously fake fixture builders. Team ids 90001+, names 'Test A'/'Test B'."""

from __future__ import annotations

import pandas as pd

HOME_ID, AWAY_ID = 90001, 90002
HOME, AWAY = "Test A", "Test B"


def game(game_id: int = 999000001, season: int = 2099, **overrides) -> dict:
    row = {
        "game_id": game_id,
        "season": season,
        "week": 1,
        "season_type": "regular",
        "start_date": pd.Timestamp("2099-09-05T18:00:00Z"),
        "completed": True,
        "neutral_site": False,
        "venue_id": 1,
        "home_id": HOME_ID,
        "home_team": HOME,
        "home_classification": "fbs",
        "home_conference": "Fake",
        "home_points": 10,
        "away_id": AWAY_ID,
        "away_team": AWAY,
        "away_classification": "fbs",
        "away_conference": "Fake",
        "away_points": 3,
        "is_final": True,
    }
    row.update(overrides)
    return row


def play(n: int, offense: str, **overrides) -> dict:
    """A raw CFBD-style play row after load_raw_plays renaming."""
    defense = AWAY if offense == HOME else HOME
    row = {
        "game_id": 999000001,
        "drive_id": "1",
        "play_id": str(999000001000 + n),
        "play_id_num": 999000001000 + n,
        "drive_number": 1,
        "play_number": n,
        "offense": offense,
        "defense": defense,
        "home": HOME,
        "away": AWAY,
        "offense_score_post": 0,
        "defense_score_post": 0,
        "period": 1,
        "clock_raw": 900 - 30 * n,
        "offense_timeouts_raw": 3,
        "defense_timeouts_raw": 3,
        "yardline": 25,
        "yards_to_goal": 75,
        "down": 1,
        "distance": 10,
        "yards_gained": 0,
        "play_type": "Rush",
        "play_text": "Fake Runner rush for 0 yards",
        "ppa": None,
        "wallclock": None,
    }
    row.update(overrides)
    return row


def state(**overrides) -> pd.DataFrame:
    row = {
        "period": 2,
        "clock_seconds": 600,
        "offense_score": 7,
        "defense_score": 3,
        "offense_timeouts": 3,
        "defense_timeouts": 2,
        "yards_to_goal": 45,
        "down": 4,
        "distance": 2,
        "home_indicator": 1,
        "offense_spread": -3.0,
        "offense_elo": 1550.0,
        "defense_elo": 1500.0,
        "season": 2099,
        "wind_speed": 5.0,
        "precipitation": 0.0,
        "elevation_m": 100.0,
        "indoors": 0,
    }
    row.update(overrides)
    return pd.DataFrame([row])
