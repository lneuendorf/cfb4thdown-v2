"""Game table: one row per completed in-scope game, keyed by CFBD/ESPN game id."""

from __future__ import annotations

import pandas as pd

from modeling.cfbd import read_cached
from modeling.config import SEASON_TYPES

COLUMNS = {
    "id": "game_id",
    "season": "season",
    "week": "week",
    "seasonType": "season_type",
    "startDate": "start_date",
    "completed": "completed",
    "neutralSite": "neutral_site",
    "venueId": "venue_id",
    "homeId": "home_id",
    "homeTeam": "home_team",
    "homeClassification": "home_classification",
    "homeConference": "home_conference",
    "homePoints": "home_points",
    "awayId": "away_id",
    "awayTeam": "away_team",
    "awayClassification": "away_classification",
    "awayConference": "away_conference",
    "awayPoints": "away_points",
}


def load_games(first_season: int, last_season: int) -> pd.DataFrame:
    frames = []
    for season in range(first_season, last_season + 1):
        for season_type in SEASON_TYPES:
            rows = read_cached(
                "games", {"year": season, "seasonType": season_type, "classification": "fbs"}
            )
            if rows:
                frames.append(pd.DataFrame(rows)[list(COLUMNS)].rename(columns=COLUMNS))
    games = pd.concat(frames, ignore_index=True).drop_duplicates("game_id")
    games["start_date"] = pd.to_datetime(games["start_date"], utc=True)
    for side in ("home", "away"):
        games[f"{side}_classification"] = games[f"{side}_classification"].fillna("unknown")
    in_scope = (games.home_classification == "fbs") | (games.away_classification == "fbs")
    games = games[in_scope].copy()
    games["is_final"] = (
        games["completed"].astype(bool) & games.home_points.notna() & games.away_points.notna()
    )
    return games.sort_values(["start_date", "game_id"]).reset_index(drop=True)
