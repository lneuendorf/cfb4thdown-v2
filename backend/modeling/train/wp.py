"""Win probability model, trained on pre-snap states for downs 1-4.

    uv run python -m modeling.train.wp [--trials 30]

Changes from v1: pre-snap scores and clock, all downs (including 1st-and-goal and 2nd/3rd
down, so the game-page chart can use every snap), chronological Elo, temporal holdout, games
failing score reconciliation or missing timeouts excluded.
"""

from __future__ import annotations

import argparse
import json
import logging

import pandas as pd
import xgboost as xgb

from modeling.config import RANDOM_SEED, TEST_SEASONS, TRAIN_SEASONS, VALID_SEASONS
from modeling.features import WP_FEATURES
from modeling.train import common

LOG = logging.getLogger("train.wp")
VERSION = "2.0.0"
MONOTONE = {
    "score_diff": 1,
    "diff_time_ratio": 1,
    "spread_time_ratio": -1,
    "offense_elo": 1,
    "defense_elo": -1,
    "home_indicator": 1,
    "offense_timeouts": 1,
    "defense_timeouts": -1,
    "yards_to_goal": -1,
    "down": -1,
    "distance": -1,
    "offense_can_kneel_out": 1,
    "opponent_can_kneel_out_after_punt": -1,
    "trailing_yards_per_second": -1,
}
PLAY_COLUMNS = [
    "game_id", "play_id", "drive_number", "play_number", "period", "clock_seconds",
    "offense_is_home", "offense_score", "defense_score", "offense_timeouts", "defense_timeouts",
    "yards_to_goal", "down", "distance", "category", "valid_state", "training_eligible_game",
    "timeouts_known",
]  # fmt: skip
STATE_KEY = [
    "period", "clock_seconds", "offense_is_home", "offense_score", "defense_score",
    "yards_to_goal", "down", "distance", "offense_timeouts", "defense_timeouts",
]  # fmt: skip


def build_training_frame() -> tuple[pd.DataFrame, dict]:
    plays = common.load_plays(PLAY_COLUMNS)
    counts = {"state_rows": int((plays["category"] != "non_state").sum())}
    keep = plays["valid_state"] & plays["training_eligible_game"] & plays["timeouts_known"]
    plays = plays[keep]
    counts["after_quality_filters"] = len(plays)
    # A "no play" penalty repeats the exact same state as the snap that follows; keep one.
    same_as_prev = (
        plays.groupby("game_id", sort=False)[STATE_KEY].shift(1).eq(plays[STATE_KEY]).all(axis=1)
    )
    plays = plays[~same_as_prev]
    counts["after_dedupe"] = len(plays)
    df = common.to_canonical_state(plays, common.load_games())
    df = df[df["offense_final_margin"] != 0]
    df["label"] = (df["offense_final_margin"] > 0).astype(int)
    counts["final"] = len(df)
    counts["games"] = int(df["game_id"].nunique())
    return df, counts


def evaluate(booster: xgb.Booster, df: pd.DataFrame) -> dict:
    p = booster.predict(xgb.DMatrix(df[WP_FEATURES]))
    y = df["label"].to_numpy()
    out = {"overall": common.binary_metrics(y, p), "calibration": common.calibration_table(y, p)}
    out["by_down"] = {
        int(d): common.binary_metrics(y[m], p[m])
        for d in (1, 2, 3, 4)
        if (m := df["down"].to_numpy() == d).any()
    }
    out["by_period"] = {
        int(q): common.binary_metrics(y[m], p[m])
        for q in (1, 2, 3, 4)
        if (m := df["period"].to_numpy() == q).any()
    }
    late_close = ((df["period"] == 4) & (df["score_diff"].abs() <= 8)).to_numpy()
    out["q4_within_8"] = common.binary_metrics(y[late_close], p[late_close])
    final_2 = ((df["period"] == 4) & (df["clock_seconds"] <= 120)).to_numpy()
    out["q4_final_2_minutes"] = common.binary_metrics(y[final_2], p[final_2])
    for lo, hi, label in ((1, 8, "leading_1_8"), (-8, -1, "trailing_1_8")):
        m = final_2 & df["score_diff"].between(lo, hi).to_numpy()
        out[f"q4_final_2_minutes_{label}"] = {
            **common.binary_metrics(y[m], p[m]),
            "mean_pred": float(p[m].mean()),
        }
    goal_to_go_first = (
        (df["down"] == 1) & (df["distance"] == df["yards_to_goal"]) & (df["yards_to_goal"] < 10)
    ).to_numpy()
    out["first_and_goal_inside_10"] = common.binary_metrics(
        y[goal_to_go_first], p[goal_to_go_first]
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=30)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    df, counts = build_training_frame()
    LOG.info("training frame: %s", counts)
    splits = common.split_by_season(df)
    base = {
        "objective": "binary:logistic",
        "tree_method": "hist",
        "nthread": -1,
        "seed": RANDOM_SEED,
        "monotone_constraints": tuple(MONOTONE.get(f, 0) for f in WP_FEATURES),
    }
    dtrain = xgb.DMatrix(splits["train"][WP_FEATURES], label=splits["train"]["label"])
    dvalid = xgb.DMatrix(splits["valid"][WP_FEATURES], label=splits["valid"]["label"])
    # Near-certain end-of-game states have tiny logistic hessians; allow small leaves. Tuned
    # configurations are indistinguishable on validation, so refit at a lower learning rate.
    tuned = common.tune_xgb(
        dtrain,
        dvalid,
        base,
        n_trials=args.trials,
        min_child_weight_range=(0.05, 200.0),
        refine_eta=0.03,
    )
    LOG.info(
        "tuned: rounds=%d valid_logloss=%.5f params=%s",
        tuned.best_rounds,
        tuned.valid_score,
        tuned.params,
    )

    # Holdout estimate: refit on train+valid seasons, score the untouched test seasons.
    train_valid = pd.concat([splits["train"], splits["valid"]])
    holdout_model = xgb.train(
        tuned.params,
        xgb.DMatrix(train_valid[WP_FEATURES], label=train_valid["label"]),
        num_boost_round=tuned.best_rounds,
    )
    test_eval = evaluate(holdout_model, splits["test"])
    LOG.info("test: %s", test_eval["overall"])

    # Production artifact: same hyperparameters, all seasons.
    final = xgb.train(
        tuned.params,
        xgb.DMatrix(df[WP_FEATURES], label=df["label"]),
        num_boost_round=tuned.best_rounds,
    )
    metadata = {
        "description": "P(offense wins) from a pre-snap game state, regulation only.",
        "features": WP_FEATURES,
        "monotone_constraints": MONOTONE,
        "label": "offense official final margin > 0 (includes overtime result)",
        "training_rows": counts,
        "seasons": {
            "all": [TRAIN_SEASONS.start, TRAIN_SEASONS.stop - 1],
            "valid": VALID_SEASONS,
            "test": TEST_SEASONS,
        },
        "tuning": {
            "n_trials": tuned.n_trials,
            "best_rounds": tuned.best_rounds,
            "valid_log_loss": tuned.valid_score,
            "params": tuned.params,
        },
        "holdout_test": test_eval,
        "in_sample_all_seasons": evaluate(final, df)["overall"],
        "data_fingerprint": common.dataset_fingerprint(df, WP_FEATURES + ["label"]),
        "filters": (
            "valid_state & training_eligible_game & timeouts_known; consecutive duplicate "
            "states dropped; tied finals dropped"
        ),
    }
    out = common.write_artifact(
        "win_probability", VERSION, {"model.json": final.save_raw("json").decode()}, metadata
    )
    LOG.info("wrote %s", out)
    print(json.dumps({"test": test_eval["overall"], "by_down": test_eval["by_down"]}, indent=2))


if __name__ == "__main__":
    main()
