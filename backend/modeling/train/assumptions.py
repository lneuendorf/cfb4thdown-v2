"""Empirical post-play assumptions for the decision (go / punt / field goal) layer.

    uv run python -m modeling.train.assumptions

v1 hard-coded several of these: an opponent start at its own 20 after any score (the data
says the 25), a conversion gaining exactly the distance, and 5 seconds of runoff for every
option. Everything the option evaluator (modeling/options.py) assumes is measured here.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from modeling.config import ARTIFACTS_DIR, TRAIN_SEASONS
from modeling.train import common, decisions

LOG = logging.getLogger("train.assumptions")
VERSION = "2.0.0"
PATH = ARTIFACTS_DIR / "decision_assumptions" / VERSION / "assumptions.json"

# Ten equal-weight quantile points represent each outcome distribution.
QUANTILES = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
YTG_BUCKETS = [(1, 10), (11, 20), (21, 40), (41, 60), (61, 99)]
DISTANCE_BUCKETS = [(1, 2), (3, 6), (7, 99)]
LATE_SECONDS = 120  # final two minutes of a half


def summarize(values: pd.Series) -> dict:
    return {
        "n": int(values.size),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "p10": float(values.quantile(0.1)),
        "p90": float(values.quantile(0.9)),
    }


def bucket_label(lo: int, hi: int) -> str:
    return f"{lo}-{hi}"


def seconds_left_in_half(df: pd.DataFrame) -> pd.Series:
    return (
        np.where(df["period"] <= 2, 2 - df["period"], 4 - df["period"]) * 900 + df["clock_seconds"]
    )


def elapsed_to_next_snap(p: pd.DataFrame) -> pd.DataFrame:
    """Seconds from each state's snap to the next state's snap, within the same period."""
    st = p[p["category"] != "non_state"]
    g = st.groupby("game_id", sort=False)
    nxt_clock = g["clock_seconds"].shift(-1)
    same_period = g["period"].shift(-1) == st["period"]
    out = st.assign(elapsed=(st["clock_seconds"] - nxt_clock).where(same_period))
    return out[out["elapsed"].between(0, 300)]


def runoff_table(frame: pd.DataFrame) -> dict:
    late = seconds_left_in_half(frame) <= LATE_SECONDS
    return {
        "median_seconds": float(frame["elapsed"].median()),
        "median_seconds_final_2_minutes_of_half": float(frame.loc[late, "elapsed"].median()),
        "n": int(len(frame)),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cols = [
        "game_id", "offense_id", "defense_id", "category", "play_type", "yards_to_goal", "down",
        "distance", "yards_gained", "next_offense_id", "next_yards_to_goal", "next_half", "half",
        "period", "clock_seconds", "offense_points_on_play", "defense_points_on_play",
        "training_eligible_game", "valid_state", "offense_timeouts", "defense_timeouts",
        "timeouts_known",
    ]  # fmt: skip
    p = common.load_plays(cols)
    p = p[p["training_eligible_game"] & p["valid_state"] & p["period"].between(1, 4)]
    same_half = p["next_half"] == p["half"]
    receiver_next = same_half & (p["next_offense_id"] == p["defense_id"])
    offense_next = same_half & (p["next_offense_id"] == p["offense_id"])
    scored_td = (p["offense_points_on_play"] >= 6) & p["category"].isin(["rush", "pass"])

    after_fg = p[(p["play_type"] == "Field Goal Good") & receiver_next]["next_yards_to_goal"]
    after_td = p[scored_td & receiver_next]["next_yards_to_goal"]

    go, _ = decisions.load_decision_plays((4,))
    go = decisions.conversion_labels(go[go["decision"] == "go"])
    converted = go[go["converted"] == 1]
    beyond = (converted["yards_gained"] - converted["distance"]).clip(lower=0)
    failed = go[
        (go["converted"] == 0)
        & (go["next_offense_id"] == go["defense_id"])
        & (go["next_half"] == go["half"])
        & (go["defense_points_on_play"] < 6)
    ]
    failed_spot = failed["next_yards_to_goal"] - (100 - failed["yards_to_goal"])
    missed = p[
        p["play_type"].isin(["Field Goal Missed", "Blocked Field Goal"])
        & receiver_next
        & (p["defense_points_on_play"] < 6)
    ]
    missed_spot = missed["next_yards_to_goal"] - (100 - missed["yards_to_goal"])

    # Distribution of yards past the line to gain on conversions (TDs included, so gains are
    # censored at the goal line), by field zone and distance.
    gain_quantiles = {}
    for ylo, yhi in YTG_BUCKETS:
        for dlo, dhi in DISTANCE_BUCKETS:
            m = converted["yards_to_goal"].between(ylo, yhi) & converted["distance"].between(
                dlo, dhi
            )
            if m.sum() >= 50:
                gain_quantiles[f"{bucket_label(ylo, yhi)}|{bucket_label(dlo, dhi)}"] = {
                    "n": int(m.sum()),
                    "yards_beyond": [float(beyond[m].quantile(q)) for q in QUANTILES],
                }

    # Snap-to-next-snap runoff by transition.
    el = elapsed_to_next_snap(p)
    transitions = {
        "conversion_same_offense": el[
            el["category"].isin(["rush", "pass"])
            & (el["down"] == 4)
            & offense_next.reindex(el.index, fill_value=False)
            & (el["offense_points_on_play"] < 6)
        ],
        "turnover_on_downs": el[
            el["category"].isin(["rush", "pass"])
            & (el["down"] == 4)
            & receiver_next.reindex(el.index, fill_value=False)
            & (el["defense_points_on_play"] < 6)
        ],
        "touchdown_then_kickoff": el[scored_td.reindex(el.index, fill_value=False)],
        "field_goal_made_then_kickoff": el[el["play_type"] == "Field Goal Good"],
        "field_goal_missed": el[el["play_type"].isin(["Field Goal Missed", "Blocked Field Goal"])],
        "punt": el[el["category"] == "punt"],
    }
    runoff = {name: runoff_table(frame) for name, frame in transitions.items()}

    # Punts: where the punt model has support.
    punts = p[p["category"] == "punt"]
    punt_counts = punts.groupby((punts["yards_to_goal"] // 5) * 5).size()
    supported = punt_counts[punt_counts >= 50]
    punt_min_ytg = int(supported.index.min())

    games = common.load_games()
    weather_defaults = decisions.weather_defaults(games)
    weather_defaults["elevation_m"] = float(games["elevation_m"].median())

    # Timeout lookup for games whose timeouts were never recorded.
    tk = p[p["timeouts_known"]].copy()
    tk["minutes_left_in_half"] = (seconds_left_in_half(tk) // 60).clip(upper=30).astype(int)
    tk_table = (
        tk.groupby(["half", "minutes_left_in_half"])[["offense_timeouts", "defense_timeouts"]]
        .median()
        .round()
        .astype(int)
    )
    timeout_lookup = {
        f"{h}|{m}": {"offense": int(r.offense_timeouts), "defense": int(r.defense_timeouts)}
        for (h, m), r in tk_table.iterrows()
    }

    out = {
        "version": VERSION,
        "seasons": [TRAIN_SEASONS.start, TRAIN_SEASONS.stop - 1],
        "opponent_start_yards_to_goal_after_made_fg": summarize(after_fg),
        "opponent_start_yards_to_goal_after_offensive_td": summarize(after_td),
        "yards_beyond_line_to_gain_on_non_td_conversion": summarize(
            beyond[converted["offense_points_on_play"] < 6]
        ),
        "failed_attempt_opponent_start_minus_line_of_scrimmage": summarize(failed_spot),
        "missed_fg_opponent_start_minus_line_of_scrimmage": {
            **summarize(missed_spot),
            "share_at_20_or_better_for_receiver": float(
                np.mean(missed["next_yards_to_goal"] <= 80)
            ),
        },
        "conversion_yards_beyond_quantiles": {
            "quantiles": QUANTILES,
            "by_ytg_and_distance": gain_quantiles,
        },
        "snap_to_next_snap_seconds": runoff,
        "punt_model_min_supported_yards_to_goal": punt_min_ytg,
        "weather_defaults": weather_defaults,
        "timeouts_median_by_half_and_minutes_left": timeout_lookup,
    }
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(out, indent=2))
    LOG.info("wrote %s", PATH)
    print(
        json.dumps(
            {k: v for k, v in out.items() if k != "timeouts_median_by_half_and_minutes_left"},
            indent=1,
        )[:4000]
    )


if __name__ == "__main__":
    main()
