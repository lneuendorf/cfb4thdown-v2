"""Pregame game context: consensus spread, weather, venue. One row per game_id."""

from __future__ import annotations

import numpy as np
import pandas as pd

from modeling.cfbd import read_cached
from modeling.config import SEASON_TYPES

# Physically plausible bounds; values outside are treated as missing, not clipped.
TEMPERATURE_F_RANGE = (-10.0, 115.0)
WIND_MPH_RANGE = (0.0, 60.0)
PRECIP_RANGE = (0.0, 3.0)


def load_spreads(seasons: range) -> pd.DataFrame:
    """Median closing spread across providers, home perspective (negative = home favored)."""
    rows = []
    for season in seasons:
        for season_type in SEASON_TYPES:
            for game in read_cached("lines", {"year": season, "seasonType": season_type}):
                spreads = [ln["spread"] for ln in game["lines"] if ln.get("spread") is not None]
                opens = [
                    ln["spreadOpen"] for ln in game["lines"] if ln.get("spreadOpen") is not None
                ]
                rows.append(
                    {
                        "game_id": game["id"],
                        "home_spread": float(np.median(spreads)) if spreads else np.nan,
                        "home_spread_open": float(np.median(opens)) if opens else np.nan,
                        "n_spread_providers": len(spreads),
                    }
                )
    return pd.DataFrame(rows).drop_duplicates("game_id")


def load_weather(seasons: range) -> pd.DataFrame:
    frames = []
    for season in seasons:
        for season_type in SEASON_TYPES:
            data = read_cached("games/weather", {"year": season, "seasonType": season_type})
            if data:
                frames.append(pd.DataFrame(data))
    w = pd.concat(frames, ignore_index=True).drop_duplicates("id")
    w = w.rename(
        columns={
            "id": "game_id",
            "gameIndoors": "game_indoors",
            "windSpeed": "wind_speed",
            "weatherConditionCode": "weather_condition_code",
        }
    )[["game_id", "game_indoors", "temperature", "wind_speed", "precipitation", "snowfall"]]
    for col, (lo, hi) in (
        ("temperature", TEMPERATURE_F_RANGE),
        ("wind_speed", WIND_MPH_RANGE),
        ("precipitation", PRECIP_RANGE),
    ):
        w[col] = pd.to_numeric(w[col], errors="coerce")
        w.loc[(w[col] < lo) | (w[col] > hi), col] = np.nan
    return w


def load_venues() -> pd.DataFrame:
    v = pd.DataFrame(read_cached("venues", {}))
    v = v.rename(columns={"id": "venue_id", "dome": "venue_dome"})
    v["elevation_m"] = pd.to_numeric(v["elevation"], errors="coerce")
    return v[["venue_id", "grass", "venue_dome", "elevation_m"]]
