"""Fourth-down (and third-down) decision datasets shared by the conversion, FG and punt models."""

from __future__ import annotations

import numpy as np
import pandas as pd

from modeling.build.plays import TURNOVER_TYPES
from modeling.config import PROCESSED_DIR
from modeling.train import common

PLAY_COLUMNS = [
    "game_id", "play_id", "drive_id", "period", "half", "clock_seconds", "offense_id",
    "defense_id", "offense_is_home", "offense_score", "defense_score", "offense_timeouts",
    "defense_timeouts", "yards_to_goal", "down", "distance", "yards_gained", "play_type",
    "play_text", "category", "valid_state", "training_eligible_game", "offense_points_on_play",
    "defense_points_on_play", "next_offense_id", "next_yards_to_goal", "next_down", "next_half",
]  # fmt: skip

WEATHER_FEATURES = ["temperature", "wind_speed", "precipitation"]
TEAM_FORM_FEATURES = [
    "offense_rush_sr",
    "offense_pass_sr",
    "defense_rush_sr_allowed",
    "defense_pass_sr_allowed",
]


def weather_defaults(games: pd.DataFrame) -> dict[str, float]:
    """Outdoor medians over training games; used when CFBD has no weather row."""
    outdoor = games[~games["game_indoors"].fillna(False).astype(bool)]
    return {c: float(outdoor[c].median()) for c in WEATHER_FEATURES}


def apply_weather(df: pd.DataFrame, defaults: dict[str, float]) -> pd.DataFrame:
    df = df.copy()
    indoors = (
        df["game_indoors"]
        .astype("boolean")
        .fillna(df["venue_dome"].astype("boolean"))
        .fillna(False)
    )
    df["indoors"] = indoors.astype(int)
    df["weather_missing"] = df["temperature"].isna().astype(int)
    for col, indoor_value in (("temperature", 70.0), ("wind_speed", 0.0), ("precipitation", 0.0)):
        df[col] = np.where(indoors, indoor_value, df[col].fillna(defaults[col]))
    df["grass"] = df["grass"].astype("boolean").fillna(False).astype(int)
    df["elevation_m"] = df["elevation_m"].fillna(defaults.get("elevation_m", 200.0))
    return df


def attach_team_form(df: pd.DataFrame) -> pd.DataFrame:
    form = pd.read_parquet(PROCESSED_DIR / "team_form.parquet")
    df = df.merge(form, on="game_id", how="left")
    home = df["offense_is_home"].to_numpy()
    df["offense_rush_sr"] = np.where(home, df["home_off_rush_sr"], df["away_off_rush_sr"])
    df["offense_pass_sr"] = np.where(home, df["home_off_pass_sr"], df["away_off_pass_sr"])
    df["defense_rush_sr_allowed"] = np.where(home, df["away_def_rush_sr"], df["home_def_rush_sr"])
    df["defense_pass_sr_allowed"] = np.where(home, df["away_def_pass_sr"], df["home_def_pass_sr"])
    return df


def load_decision_plays(downs: tuple[int, ...] = (4,)) -> tuple[pd.DataFrame, dict]:
    plays = common.load_plays(PLAY_COLUMNS)
    plays = plays[
        plays["down"].isin(downs)
        & plays["valid_state"]
        & plays["training_eligible_game"]
        & plays["period"].between(1, 4)
    ]
    games = common.load_games()
    defaults = weather_defaults(games)
    defaults["elevation_m"] = float(games["elevation_m"].median())
    df = common.to_canonical_state(plays, games)
    df = apply_weather(df, defaults)
    df = attach_team_form(df)
    df["decision"] = np.select(
        [
            df["category"].isin(["rush", "pass", "fumble", "safety"]),
            df["category"].eq("punt"),
            df["category"].eq("field_goal"),
        ],
        ["go", "punt", "field_goal"],
        default="excluded",
    )
    return df, defaults


def conversion_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Success = offensive TD, or gained the distance without a turnover or safety."""
    df = df.copy()
    offense_td = df["offense_points_on_play"] >= 6
    turnover = df["play_type"].isin(TURNOVER_TYPES) | df["category"].eq("safety")
    df["converted"] = (offense_td | ((df["yards_gained"] >= df["distance"]) & ~turnover)).astype(
        int
    )
    # Cross-check against the next recorded state: same offense with a fresh first down.
    has_next = df["next_offense_id"].notna() & (df["next_half"] == df["half"])
    next_says = (df["next_offense_id"] == df["offense_id"]) & (df["next_down"] == 1)
    df["label_check"] = np.where(offense_td, 1, np.where(has_next, next_says.astype(int), -1))
    return df
