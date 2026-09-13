"""Fourth-down conversion model.

    uv run python -m modeling.train.conversion [--trials 25]

Label: offensive TD, or gained the distance without a turnover/safety (98% agreement with the
next recorded state). Inputs are pre-snap. Feature groups are chosen by ablation on the
validation seasons, scored on fourth downs only.
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

LOG = logging.getLogger("train.conversion")
VERSION = "2.0.0"

BASE = ["distance", "yards_to_goal", "diff_time_ratio", "home_indicator"]
ELO = ["offense_elo", "defense_elo"]
WEATHER = ["temperature", "wind_speed", "precipitation", "indoors"]
FORM = decisions.TEAM_FORM_FEATURES
CONFIGS = {
    "A_situation_elo": (BASE + ELO, (4,)),
    "B_plus_weather": (BASE + ELO + WEATHER, (4,)),
    "C_plus_team_form": (BASE + ELO + FORM, (4,)),
    "D_plus_form_weather": (BASE + ELO + FORM + WEATHER, (4,)),
    "E_form_weather_3rd_and_4th": (BASE + ELO + FORM + WEATHER + ["is_fourth_down"], (3, 4)),
}
MONOTONE = {
    "distance": -1,
    "home_indicator": 1,
    "offense_elo": 1,
    "defense_elo": -1,
    "offense_rush_sr": 1,
    "offense_pass_sr": 1,
    "defense_rush_sr_allowed": 1,
    "defense_pass_sr_allowed": 1,
    "wind_speed": -1,
    "precipitation": -1,
}
FIXED_PARAMS = {
    "eta": 0.05,
    "max_depth": 4,
    "min_child_weight": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "lambda": 1.0,
}


def build_frame() -> pd.DataFrame:
    df, _ = decisions.load_decision_plays(downs=(3, 4))
    df = df[df["decision"] == "go"]
    df = decisions.conversion_labels(df)
    df["is_fourth_down"] = (df["down"] == 4).astype(int)
    # Early 2013 has no team-form ratings (no 2012 plays); drop so every config sees the same rows.
    return df[df[FORM].notna().all(axis=1)].reset_index(drop=True)


def base_params(features: list[str]) -> dict:
    return {
        "objective": "binary:logistic",
        "tree_method": "hist",
        "nthread": -1,
        "seed": RANDOM_SEED,
        "monotone_constraints": tuple(MONOTONE.get(f, 0) for f in features),
    }


def fit_eval(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    features: list[str],
    params: dict,
    rounds: int | None = None,
) -> tuple[xgb.Booster, float, int]:
    dtrain = xgb.DMatrix(train[features], label=train["converted"])
    v4 = valid[valid["down"] == 4]
    dvalid = xgb.DMatrix(v4[features], label=v4["converted"])
    if rounds is None:
        booster = xgb.train(
            {**params, "eval_metric": "logloss"},
            dtrain,
            3000,
            evals=[(dvalid, "valid")],
            early_stopping_rounds=100,
            verbose_eval=False,
        )
        rounds = booster.best_iteration + 1
    else:
        booster = xgb.train(params, dtrain, rounds)
    p = booster.predict(dvalid, iteration_range=(0, rounds))
    return booster, common.log_loss(v4["converted"].to_numpy(), p), rounds


def baseline_by_distance(train: pd.DataFrame, target: pd.DataFrame) -> np.ndarray:
    buckets = lambda d: np.minimum(d, 15)  # noqa: E731
    rate = (
        train[train["down"] == 4]
        .groupby(buckets(train.loc[train["down"] == 4, "distance"]))["converted"]
        .mean()
    )
    return buckets(target["distance"]).map(rate).fillna(train["converted"].mean()).to_numpy()


def evaluate(booster: xgb.Booster, df: pd.DataFrame, features: list[str]) -> dict:
    d4 = df[df["down"] == 4]
    p = booster.predict(xgb.DMatrix(d4[features]))
    y = d4["converted"].to_numpy()
    by_distance = {}
    for label, lo, hi in (
        ("1", 1, 1),
        ("2-3", 2, 3),
        ("4-6", 4, 6),
        ("7-10", 7, 10),
        ("11+", 11, 99),
    ):
        m = d4["distance"].between(lo, hi).to_numpy()
        by_distance[label] = {
            "n": int(m.sum()),
            "pred": float(p[m].mean()),
            "obs": float(y[m].mean()),
        }
    return {
        "overall": common.binary_metrics(y, p),
        "calibration": common.calibration_table(y, p),
        "by_distance": by_distance,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=25)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    df = build_frame()
    splits = common.split_by_season(df)
    LOG.info("rows: %s", {k: int((v["down"] == 4).sum()) for k, v in splits.items()})

    ablation = {}
    for name, (features, downs) in CONFIGS.items():
        train = splits["train"][splits["train"]["down"].isin(downs)]
        _, ll, rounds = fit_eval(
            train, splits["valid"], features, {**base_params(features), **FIXED_PARAMS}
        )
        ablation[name] = {"valid_log_loss_4th": ll, "rounds": rounds, "train_rows": len(train)}
        LOG.info("ablation %s: %.5f (%d rounds)", name, ll, rounds)
    v4 = splits["valid"][splits["valid"]["down"] == 4]
    ablation["baseline_distance_rate"] = {
        "valid_log_loss_4th": common.log_loss(
            v4["converted"].to_numpy(), baseline_by_distance(splits["train"], v4)
        )
    }

    # Prefer the simplest config within 0.001 log loss of the best.
    scored = {k: v["valid_log_loss_4th"] for k, v in ablation.items() if k in CONFIGS}
    best = min(scored.values())
    chosen = next(k for k in CONFIGS if scored[k] <= best + 0.001)
    features, downs = CONFIGS[chosen]
    LOG.info("chosen config: %s", chosen)

    train = splits["train"][splits["train"]["down"].isin(downs)]
    valid4 = splits["valid"][splits["valid"]["down"] == 4]
    tuned = common.tune_xgb(
        xgb.DMatrix(train[features], label=train["converted"]),
        xgb.DMatrix(valid4[features], label=valid4["converted"]),
        base_params(features),
        n_trials=args.trials,
    )
    train_valid = pd.concat([splits["train"], splits["valid"]])
    train_valid = train_valid[train_valid["down"].isin(downs)]
    holdout = xgb.train(
        tuned.params,
        xgb.DMatrix(train_valid[features], label=train_valid["converted"]),
        tuned.best_rounds,
    )
    test_eval = evaluate(holdout, splits["test"], features)
    t4 = splits["test"][splits["test"]["down"] == 4]
    test_eval["baseline_distance_rate_log_loss"] = common.log_loss(
        t4["converted"].to_numpy(), baseline_by_distance(train_valid, t4)
    )
    LOG.info("test: %s", test_eval["overall"])

    all_rows = df[df["down"].isin(downs)]
    final = xgb.train(
        tuned.params,
        xgb.DMatrix(all_rows[features], label=all_rows["converted"]),
        tuned.best_rounds,
    )
    metadata = {
        "description": "P(fourth-down attempt gains a first down or TD without a turnover).",
        "features": features,
        "config": chosen,
        "training_downs": list(downs),
        "monotone_constraints": {f: MONOTONE[f] for f in features if f in MONOTONE},
        "ablation_valid": ablation,
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
        "holdout_test_4th_down": test_eval,
        "training_rows": {"all": len(all_rows), "fourth_down": int((all_rows["down"] == 4).sum())},
        "data_fingerprint": common.dataset_fingerprint(all_rows, features + ["converted"]),
    }
    out = common.write_artifact(
        "conversion", VERSION, {"model.json": final.save_raw("json").decode()}, metadata
    )
    LOG.info("wrote %s", out)
    print(
        json.dumps(
            {
                "ablation": ablation,
                "chosen": chosen,
                "test": test_eval["overall"],
                "by_distance": test_eval["by_distance"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
