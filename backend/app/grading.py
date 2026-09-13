"""Recommendation, verdict and confidence for graded fourth downs.

Thresholds live here and only here (docs/data-pipeline.md, Stage 4). The frontend must never
re-derive a verdict; it reads the stored one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OPTIONS = ("go", "field_goal", "punt")
OPTION_COLUMNS = {"go": "wp_go", "field_goal": "wp_field_goal", "punt": "wp_punt"}

# Verdicts (docs/api-contract.md, Decision object).
MISTAKE_THRESHOLD = 0.05

# Confidence of a recommendation from its margin over the next-best feasible option
# (docs/api-contract.md, Simulator).
CONFIDENCE_CLEAR_MARGIN = 0.05
CONFIDENCE_CLOSE_MARGIN = 0.02

# Garbage time (docs/data-pipeline.md, Stage 2): pre-snap WP outside these bounds with under
# five minutes left in the game.
GARBAGE_TIME_SECONDS = 300
GARBAGE_TIME_WP_LOW = 0.01
GARBAGE_TIME_WP_HIGH = 0.99


def recommend(options: pd.DataFrame) -> pd.DataFrame:
    """Best feasible option, its margin over the runner-up, and a confidence label.

    Infeasible options are NaN and never recommended. An exact tie resolves in OPTIONS order;
    with continuous probabilities that is vanishingly rare and not treated specially.
    """
    wp = options[[OPTION_COLUMNS[o] for o in OPTIONS]].to_numpy(dtype=float)
    filled = np.where(np.isnan(wp), -np.inf, wp)
    best_idx = filled.argmax(axis=1)
    ordered = np.sort(filled, axis=1)
    best = ordered[:, -1]
    runner_up = ordered[:, -2]
    margin = np.where(np.isfinite(runner_up), best - runner_up, np.nan)
    confidence = np.select(
        [margin >= CONFIDENCE_CLEAR_MARGIN, margin >= CONFIDENCE_CLOSE_MARGIN, np.isfinite(margin)],
        ["clear", "close", "toss_up"],
        default="only_option",
    )
    return pd.DataFrame(
        {
            "recommendation": np.array(OPTIONS)[best_idx],
            "wp_recommended": best,
            "margin": margin,
            "confidence": confidence,
        },
        index=options.index,
    )


def grade(decision: pd.Series, options: pd.DataFrame, recommendation: pd.DataFrame) -> pd.DataFrame:
    """wp_delta = WP(actual decision) - WP(recommended); verdict per the contract."""
    actual = np.full(len(options), np.nan)
    for option, col in OPTION_COLUMNS.items():
        mask = (decision == option).to_numpy()
        actual[mask] = options.loc[mask, col].to_numpy()
    delta = actual - recommendation["wp_recommended"].to_numpy()
    matched = decision.to_numpy() == recommendation["recommendation"].to_numpy()
    verdict = np.select(
        [np.isnan(delta), matched, np.abs(delta) >= MISTAKE_THRESHOLD],
        ["ungraded", "correct", "mistake"],
        default="marginal",
    )
    delta = np.where(matched, 0.0, delta)
    return pd.DataFrame(
        {"wp_actual": actual, "wp_delta": delta, "verdict": verdict}, index=options.index
    )


def is_garbage_time(game_seconds_remaining: pd.Series, pre_snap_wp: pd.Series) -> pd.Series:
    return (game_seconds_remaining < GARBAGE_TIME_SECONDS) & (
        (pre_snap_wp < GARBAGE_TIME_WP_LOW) | (pre_snap_wp > GARBAGE_TIME_WP_HIGH)
    )
