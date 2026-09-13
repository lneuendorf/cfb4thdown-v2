"""Shared grading pipeline for batch (CFBD) and live (ESPN) fourth downs.

Input: canonical pre-snap states (modeling.features) plus pregame context columns
(offense_spread, offense_elo, defense_elo, home_indicator, season, wind_speed, precipitation,
elevation_m, indoors) and a play `category` from modeling.build.plays.categorize.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app import grading
from modeling import inference, options

GO_CATEGORIES = ("rush", "pass", "fumble", "safety")


def classify_decision(category: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [category.isin(GO_CATEGORIES), category.eq("punt"), category.eq("field_goal")],
            ["go", "punt", "field_goal"],
            default="",
        ),
        index=category.index,
    )


def category_exclusion(category: pd.Series) -> pd.Series:
    """Reasons that depend only on what kind of play it was."""
    return pd.Series(
        np.select(
            [
                category.eq("penalty"),
                category.isin(["kneel", "spike"]),
                category.isin(["other", "non_state"]),
            ],
            ["penalty_no_decision", "kneel_or_spike", "unclassified_play"],
            default="",
        ),
        index=category.index,
    )


def model_scope_exclusion(state: pd.DataFrame) -> pd.Series:
    """Reasons that need the pre-snap WP and the decision: model range and garbage time."""
    punt_min = options.assumptions()["punt_model_min_supported_yards_to_goal"]
    return pd.Series(
        np.select(
            [
                (state["decision"] == "field_goal")
                & (state["yards_to_goal"] > options.FIELD_GOAL_MAX_YARDS_TO_GOAL),
                (state["decision"] == "punt") & (state["yards_to_goal"] < punt_min),
                grading.is_garbage_time(state["game_seconds_remaining"], state["pre_snap_wp"]),
            ],
            ["field_goal_outside_model_range", "punt_outside_model_range", "garbage_time"],
            default="",
        ),
        index=state.index,
    )


def evaluate(state: pd.DataFrame) -> pd.DataFrame:
    """Options and recommendation for pre-snap fourth-down states (no decision needed)."""
    opts = options.evaluate_options(state)
    rec = grading.recommend(opts)
    return pd.concat([opts, rec], axis=1)


def grade_decisions(state: pd.DataFrame) -> pd.DataFrame:
    """Options, recommendation and verdict for states with a `decision` column."""
    evaluated = evaluate(state)
    g = grading.grade(state["decision"], evaluated, evaluated)
    return pd.concat([evaluated, g], axis=1)


def model_versions() -> dict:
    return {**inference.MODEL_VERSIONS, "decision_assumptions": options.ASSUMPTIONS_VERSION}
