"""Feature functions shared by training and inference.

Every model consumes a canonical pre-snap game state. Training builds that state from CFBD
play-by-play; live inference will build it from ESPN. The functions here are the only place
derived features are computed, so both paths produce identical inputs.

Canonical state columns (all from the offense's perspective, all pre-snap):
    period                 1-4 (regulation only)
    clock_seconds          seconds remaining in the period
    offense_score, defense_score
    offense_timeouts, defense_timeouts   0-3
    yards_to_goal          1-99, offense perspective
    down                   1-4
    distance               yards to first down, 1..yards_to_goal
    home_indicator         1 offense at home, -1 offense away, 0 neutral site
    offense_spread         closing spread from the offense's perspective (negative = favored)
    offense_elo, defense_elo   pregame Elo
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PERIOD_SECONDS = 900
GAME_SECONDS = 3600
PLAY_CLOCK_SECONDS = 40
KNEEL_SECONDS = 2
PUNT_SECONDS = 7

WP_FEATURES = [
    "score_diff",
    "offense_score",
    "defense_score",
    "diff_time_ratio",
    "spread_time_ratio",
    "offense_elo",
    "defense_elo",
    "pct_game_played",
    "seconds_left_in_half",
    "home_indicator",
    "offense_timeouts",
    "defense_timeouts",
    "yards_to_goal",
    "down",
    "distance",
    "seconds_after_kneelout",
    "seconds_after_punt_and_opponent_kneelout",
    "offense_can_kneel_out",
    "opponent_can_kneel_out_after_punt",
    "trailing_yards_per_second",
]


def game_seconds_remaining(period: pd.Series, clock_seconds: pd.Series) -> pd.Series:
    return (4 - period) * PERIOD_SECONDS + clock_seconds


def seconds_left_in_half(period: pd.Series, clock_seconds: pd.Series) -> pd.Series:
    return np.where(period <= 2, (2 - period), (4 - period)) * PERIOD_SECONDS + clock_seconds


def kneelout_seconds_remaining(
    seconds: np.ndarray, defense_timeouts: np.ndarray, down: np.ndarray
) -> np.ndarray:
    """Seconds left after the offense kneels on every remaining down.

    College rules: no two-minute warning (v1 used the NFL rule). Each kneel takes
    KNEEL_SECONDS; the offense then lets the full play clock run unless the defense calls a
    timeout, which stops the clock until the next snap.
    """
    seconds = np.asarray(seconds, dtype=float).copy()
    timeouts = np.nan_to_num(np.asarray(defense_timeouts, dtype=float)).copy()
    downs_left = 4 - np.asarray(down, dtype=float) + 1
    for _ in range(4):
        active = (seconds > 0) & (downs_left > 0)
        seconds = np.where(active, seconds - KNEEL_SECONDS, seconds)
        use_timeout = active & (timeouts > 0) & (downs_left > 1)
        timeouts = np.where(use_timeout, timeouts - 1, timeouts)
        runoff = active & ~use_timeout & (downs_left > 1)
        seconds = np.where(runoff, seconds - PLAY_CLOCK_SECONDS, seconds)
        downs_left = np.where(active, downs_left - 1, downs_left)
    return np.maximum(seconds, 0)


def add_state_features(state: pd.DataFrame) -> pd.DataFrame:
    """Add every derived feature used by any model. Input must have the canonical columns."""
    df = state.copy()
    df["distance"] = np.minimum(df["distance"], df["yards_to_goal"])
    df["score_diff"] = df["offense_score"] - df["defense_score"]
    df["elo_diff"] = df["offense_elo"] - df["defense_elo"]
    gsr = game_seconds_remaining(df["period"], df["clock_seconds"])
    df["game_seconds_remaining"] = gsr
    df["pct_game_played"] = 1 - gsr / GAME_SECONDS
    df["seconds_left_in_half"] = seconds_left_in_half(df["period"], df["clock_seconds"])
    df["diff_time_ratio"] = df["score_diff"] * np.exp(4 * df["pct_game_played"])
    df["spread_time_ratio"] = df["offense_spread"] * np.exp(-4 * df["pct_game_played"])
    df["seconds_after_kneelout"] = kneelout_seconds_remaining(
        gsr.to_numpy(), df["defense_timeouts"].to_numpy(), df["down"].to_numpy()
    )
    after_punt = np.maximum(gsr.to_numpy() - PUNT_SECONDS, 0)
    opp_kneel = kneelout_seconds_remaining(
        after_punt, df["offense_timeouts"].to_numpy(), np.ones(len(df))
    )
    df["seconds_after_punt_and_opponent_kneelout"] = np.maximum(opp_kneel - PUNT_SECONDS, 0)
    # Explicit end-of-game indicators. Trees cannot learn "the leader kneels it out" from the
    # continuous inputs alone: those states are rare and near-certain, so their tiny logistic
    # hessians never reach min_child_weight (v2.0.0 draft predicted 0.87 where the rate is 0.99).
    df["offense_can_kneel_out"] = (
        (df["score_diff"] > 0) & (df["seconds_after_kneelout"] <= 0)
    ).astype(int)
    df["opponent_can_kneel_out_after_punt"] = (
        (df["score_diff"] < 0) & (df["seconds_after_punt_and_opponent_kneelout"] <= 0)
    ).astype(int)
    # How much field a trailing offense must cover per second left; 0 when not trailing.
    df["trailing_yards_per_second"] = np.where(
        df["score_diff"] < 0, df["yards_to_goal"] / (gsr + 1), 0.0
    )
    df["pressure_rating"] = pressure_rating(gsr, df["score_diff"])
    return df


def pressure_rating(game_seconds_remaining: pd.Series, score_diff: pd.Series) -> np.ndarray:
    """Kick pressure scale 0-4 (ported from v1): late, and a make ties/takes the lead."""
    gsr, sd = game_seconds_remaining, score_diff
    tie_or_lead = (sd >= -3) & (sd <= 0)
    one_score = (sd >= -11) & (sd <= -4)
    return np.select(
        [
            (gsr <= 120) & tie_or_lead,
            ((gsr <= 300) & tie_or_lead) | ((gsr <= 120) & one_score),
            ((gsr <= 600) & tie_or_lead) | ((gsr <= 300) & one_score),
            ((gsr <= 900) & tie_or_lead) | ((gsr <= 600) & one_score),
            (gsr <= 900) & one_score,
        ],
        [4.0, 3.0, 2.0, 1.0, 0.5],
        default=0.0,
    )


def flip_possession(state: pd.DataFrame) -> pd.DataFrame:
    """Swap offense and defense in a canonical state (yards_to_goal is left to the caller)."""
    df = state.copy()
    for a, b in (
        ("offense_score", "defense_score"),
        ("offense_timeouts", "defense_timeouts"),
        ("offense_elo", "defense_elo"),
    ):
        df[a], df[b] = state[b].to_numpy(), state[a].to_numpy()
    df["home_indicator"] = -state["home_indicator"]
    df["offense_spread"] = -state["offense_spread"]
    return df
