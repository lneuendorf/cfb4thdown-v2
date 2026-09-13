"""Reference data read from the database, so scheduled jobs don't need the raw CFBD cache.

jobs.backfill writes every game since ELO_FIRST_SEASON and the venue table. A server that only
has the database, the model artifacts and a CFBD key can therefore replay Elo and look up
venues. Where the database has nothing yet, these fall back to the local raw cache.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from modeling.build import context
from modeling.build.games import load_games
from modeling.config import ELO_FIRST_SEASON


def final_games_through(conn: sqlite3.Connection, last_season: int) -> pd.DataFrame:
    """Final games from ELO_FIRST_SEASON through `last_season`, in kickoff order."""
    games = pd.read_sql_query(
        "SELECT * FROM games WHERE season BETWEEN ? AND ? AND is_final = 1",
        conn,
        params=(ELO_FIRST_SEASON, last_season),
    )
    if games.empty or int(games["season"].min()) > ELO_FIRST_SEASON:
        raw = load_games(ELO_FIRST_SEASON, last_season)
        return raw[raw["is_final"]].reset_index(drop=True)
    games["start_date"] = pd.to_datetime(games["start_date"], utc=True, format="ISO8601")
    games["neutral_site"] = games["neutral_site"].astype(bool)
    games["is_final"] = games["is_final"].astype(bool)
    return games.sort_values(["start_date", "game_id"]).reset_index(drop=True)


def venues(conn: sqlite3.Connection) -> pd.DataFrame:
    """venue_id, grass, venue_dome, elevation_m (context.load_venues shape)."""
    v = pd.read_sql_query(
        "SELECT venue_id, grass, dome AS venue_dome, elevation_m FROM venues", conn
    )
    if v.empty:
        return context.load_venues()
    for col in ("grass", "venue_dome"):
        v[col] = v[col].astype("boolean")
    return v
