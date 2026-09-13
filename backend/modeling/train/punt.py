"""Punt outcome model: receiving team's yards to goal on its next snap.

    uv run python -m modeling.train.punt [--trials 20]

Target, from play-by-play: the receiving team's pre-snap yards_to_goal on its first state
after the punt (touchbacks, returns and return penalties included); 0 for a return TD.
Punts where the kicking team keeps the ball (muffs, re-kicks) or the half ends are excluded
and counted. Unlike v1 there is no hard-coded 80 for punts inside the 40: the model learns
touchback rates from the data. Residual quantiles are saved so expected WP can integrate over
the outcome distribution later instead of plugging in the mean.
"""

from __future__ import annotations

import argparse
import json
import logging

import numpy as np
import pandas as pd
import xgboost as xgb

from modeling.config import RANDOM_SEED, TEST_SEASONS, TRAIN_SEASONS, VALID_SEASONS
from modeling.train import common, decisions

LOG = logging.getLogger("train.punt")
VERSION = "2.0.0"
BASE = ["yards_to_goal", "offense_elo", "defense_elo"]
WEATHER = ["wind_speed", "temperature", "precipitation", "elevation_m", "indoors"]
MONOTONE = {
    "yards_to_goal": -1,
    "offense_elo": 1,
    "defense_elo": -1,
    "wind_speed": -1,
    "elevation_m": 1,
}
FIXED = {
    "eta": 0.05,
    "max_depth": 4,
    "min_child_weight": 30,
    "subsample": 0.8,
    "colsample_bytree": 0.9,
}


def build_frame() -> tuple[pd.DataFrame, dict]:
    df, _ = decisions.load_decision_plays((4,))
    df = df[df["decision"] == "punt"].copy()
    counts = {"punts": len(df)}
    return_td = df["defense_points_on_play"] >= 6
    receiver_next = (df["next_offense_id"] == df["defense_id"]) & (df["next_half"] == df["half"])
    kicker_keeps = (
        (df["next_offense_id"] == df["offense_id"]) & (df["next_half"] == df["half"]) & ~return_td
    )
    df["receiving_yards_to_goal"] = np.where(
        return_td, 0.0, np.where(receiver_next, df["next_yards_to_goal"], np.nan)
    )
    counts["return_td"] = int(return_td.sum())
    counts["kicking_team_keeps_ball"] = int(kicker_keeps.sum())
    counts["no_next_state_in_half"] = int((~return_td & ~receiver_next & ~kicker_keeps).sum())
    df = df[df["receiving_yards_to_goal"].notna()]
    counts["used"] = len(df)
    return df.reset_index(drop=True), counts


def params_for(features: list[str]) -> dict:
    return {
        "objective": "reg:squarederror",
        "tree_method": "hist",
        "nthread": -1,
        "seed": RANDOM_SEED,
        "eval_metric": "rmse",
        "monotone_constraints": tuple(MONOTONE.get(f, 0) for f in features),
    }


def regression_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    return {
        "n": int(len(y)),
        "rmse": float(np.sqrt(np.mean((p - y) ** 2))),
        "mae": float(np.mean(np.abs(p - y))),
        "bias": float(np.mean(p - y)),
    }


def by_bucket(df: pd.DataFrame, p: np.ndarray) -> dict:
    out = {}
    for label, lo, hi in (
        ("<35", 1, 34),
        ("35-44", 35, 44),
        ("45-59", 45, 59),
        ("60-74", 60, 74),
        ("75+", 75, 99),
    ):
        m = df["yards_to_goal"].between(lo, hi).to_numpy()
        y = df["receiving_yards_to_goal"].to_numpy()[m]
        out[label] = {
            **regression_metrics(y, p[m]),
            "mean_obs": float(y.mean()),
            "mean_pred": float(p[m].mean()),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=20)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    df, counts = build_frame()
    LOG.info("punts: %s", counts)
    splits = common.split_by_season(df)
    target = "receiving_yards_to_goal"

    ablation = {}
    for name, feats in (("base", BASE), ("base_weather", BASE + WEATHER)):
        dtr = xgb.DMatrix(splits["train"][feats], label=splits["train"][target])
        dva = xgb.DMatrix(splits["valid"][feats], label=splits["valid"][target])
        b = xgb.train(
            {**params_for(feats), **FIXED},
            dtr,
            3000,
            evals=[(dva, "v")],
            early_stopping_rounds=100,
            verbose_eval=False,
        )
        ablation[name] = {"valid_rmse": float(b.best_score), "rounds": b.best_iteration + 1}
    bucket_mean = splits["train"].groupby(splits["train"]["yards_to_goal"] // 5)[target].mean()
    base_pred = (splits["valid"]["yards_to_goal"] // 5).map(bucket_mean).to_numpy()
    ablation["baseline_bucket_mean"] = regression_metrics(
        splits["valid"][target].to_numpy(), base_pred
    )
    LOG.info("ablation: %s", ablation)
    features = (
        BASE + WEATHER
        if ablation["base_weather"]["valid_rmse"] < ablation["base"]["valid_rmse"] - 0.05
        else BASE
    )

    tuned = common.tune_xgb(
        xgb.DMatrix(splits["train"][features], label=splits["train"][target]),
        xgb.DMatrix(splits["valid"][features], label=splits["valid"][target]),
        params_for(features),
        n_trials=args.trials,
        eval_metric="rmse",
    )
    tv = pd.concat([splits["train"], splits["valid"]])
    holdout = xgb.train(
        tuned.params, xgb.DMatrix(tv[features], label=tv[target]), tuned.best_rounds
    )
    p_test = holdout.predict(xgb.DMatrix(splits["test"][features]))
    y_test = splits["test"][target].to_numpy()
    test_eval = {
        "overall": regression_metrics(y_test, p_test),
        "by_punt_yards_to_goal": by_bucket(splits["test"], p_test),
    }

    final = xgb.train(tuned.params, xgb.DMatrix(df[features], label=df[target]), tuned.best_rounds)
    resid = df[target].to_numpy() - final.predict(xgb.DMatrix(df[features]))
    qs = [0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95]
    residual_quantiles = {
        label: [float(np.quantile(resid[m], q)) for q in qs]
        for label, lo, hi in (
            ("<35", 1, 34),
            ("35-44", 35, 44),
            ("45-59", 45, 59),
            ("60-74", 60, 74),
            ("75+", 75, 99),
        )
        if (m := df["yards_to_goal"].between(lo, hi).to_numpy()).any()
    }
    metadata = {
        "description": (
            "Expected receiving-team yards_to_goal on its next snap after a punt (0 = return TD)."
        ),
        "features": features,
        "monotone_constraints": {f: MONOTONE[f] for f in features if f in MONOTONE},
        "target_counts": counts,
        "ablation_valid": ablation,
        "seasons": {
            "all": [TRAIN_SEASONS.start, TRAIN_SEASONS.stop - 1],
            "valid": VALID_SEASONS,
            "test": TEST_SEASONS,
        },
        "tuning": {
            "n_trials": tuned.n_trials,
            "best_rounds": tuned.best_rounds,
            "valid_rmse": tuned.valid_score,
            "params": tuned.params,
        },
        "holdout_test": test_eval,
        "residual_quantiles": {"quantiles": qs, "by_punt_yards_to_goal": residual_quantiles},
        "data_fingerprint": common.dataset_fingerprint(df, features + [target]),
    }
    out = common.write_artifact(
        "punt", VERSION, {"model.json": final.save_raw("json").decode()}, metadata
    )
    LOG.info("wrote %s", out)
    print(
        json.dumps(
            {"counts": counts, "ablation": ablation, "features": features, "test": test_eval},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
