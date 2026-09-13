"""Field goal make probability.

    uv run python -m modeling.train.field_goal

v1 used a two-stage Heckman probit: coaches attempt kicks selectively, so stage 1 models
P(attempt) and stage 2 models P(make) with the inverse Mills ratio as a covariate. This script
still fits that correction as a diagnostic, with v1's two defects fixed (Mills ratio from the
linear index; each scaler fit on raw columns). On clean pre-snap data the correction is
estimated at ~0 and does not change validation log loss, so the shipped model is a probit on
attempts only. Coefficients are exported to JSON; no statsmodels pickle is needed to predict.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm

from modeling.config import TEST_SEASONS, TRAIN_SEASONS, VALID_SEASONS
from modeling.train import common, decisions

LOG = logging.getLogger("train.field_goal")
VERSION = "2.0.0"
MAX_YARDS_TO_GOAL = 50  # 67-yard kick

SELECTION_CONTINUOUS = [
    "yards_to_goal", "distance", "score_diff", "pct_game_played", "offense_elo", "defense_elo",
    "wind_speed", "temperature", "elevation_m",
]  # fmt: skip
SELECTION_BINARY = ["home_indicator", "grass", "indoors"]
OUTCOME_CONTINUOUS = [
    "yards_to_goal", "yards_to_goal_sq", "offense_elo", "wind_speed", "precipitation",
    "elevation_m", "season",
]  # fmt: skip
OUTCOME_BINARY = ["indoors"]


def build_frame() -> pd.DataFrame:
    df, _ = decisions.load_decision_plays((4,))
    df = df[
        df["decision"].isin(["go", "punt", "field_goal"])
        & (df["yards_to_goal"] <= MAX_YARDS_TO_GOAL)
    ]
    df = df.copy()
    df["attempt"] = (df["decision"] == "field_goal").astype(int)
    df["made"] = (df["play_type"] == "Field Goal Good").astype(int)
    df["yards_to_goal_sq"] = df["yards_to_goal"] ** 2
    return df.reset_index(drop=True)


def standardize(train: pd.DataFrame, cols: list[str]) -> dict[str, dict[str, float]]:
    return {c: {"mean": float(train[c].mean()), "std": float(train[c].std())} for c in cols}


def design(df: pd.DataFrame, scale: dict, continuous: list[str], binary: list[str]) -> pd.DataFrame:
    X = pd.DataFrame({c: (df[c] - scale[c]["mean"]) / scale[c]["std"] for c in continuous})
    for c in binary:
        X[c] = df[c].astype(float)
    return sm.add_constant(X, has_constant="add")


def mills(linear_index: np.ndarray) -> np.ndarray:
    return norm.pdf(linear_index) / np.clip(norm.cdf(linear_index), 1e-12, None)


def fit(train: pd.DataFrame, with_selection: bool = True) -> dict:
    sel_scale = standardize(train, SELECTION_CONTINUOUS)
    sel = sm.Probit(
        train["attempt"], design(train, sel_scale, SELECTION_CONTINUOUS, SELECTION_BINARY)
    ).fit(disp=0)
    attempts = train[train["attempt"] == 1]
    out_scale = standardize(attempts, OUTCOME_CONTINUOUS)
    X_out = design(attempts, out_scale, OUTCOME_CONTINUOUS, OUTCOME_BINARY)
    if with_selection:
        xb = (
            design(attempts, sel_scale, SELECTION_CONTINUOUS, SELECTION_BINARY).to_numpy()
            @ sel.params.to_numpy()
        )
        X_out["mills_ratio"] = mills(xb)
    out = sm.Probit(attempts["made"], X_out).fit(disp=0)
    return {
        "selection": {
            "scale": sel_scale,
            "binary": SELECTION_BINARY,
            "coef": sel.params.to_dict(),
            "pseudo_r2": float(sel.prsquared),
            "n": int(sel.nobs),
        },
        "outcome": {
            "scale": out_scale,
            "binary": OUTCOME_BINARY,
            "coef": out.params.to_dict(),
            "pseudo_r2": float(out.prsquared),
            "n": int(out.nobs),
            "season_clamp": [int(train["season"].min()), int(train["season"].max()) + 1],
        },
        "with_selection": with_selection,
    }


def predict_make(model: dict, df: pd.DataFrame) -> np.ndarray:
    """Same math the inference module uses; kept here so training metrics use it too."""
    df = df.copy()
    lo, hi = model["outcome"]["season_clamp"]
    df["season"] = df["season"].clip(lo, hi)
    df["yards_to_goal_sq"] = df["yards_to_goal"] ** 2

    def linear(stage: dict, continuous: list[str]) -> np.ndarray:
        coef = stage["coef"]
        total = np.full(len(df), coef["const"])
        for c in continuous:
            s = stage["scale"][c]
            total += coef[c] * (df[c].to_numpy() - s["mean"]) / s["std"]
        for c in stage["binary"]:
            total += coef[c] * df[c].to_numpy()
        return total

    xb_out = linear(model["outcome"], OUTCOME_CONTINUOUS)
    if model["with_selection"]:
        xb_sel = linear(model["selection"], SELECTION_CONTINUOUS)
        xb_out = xb_out + model["outcome"]["coef"]["mills_ratio"] * mills(xb_sel)
    return norm.cdf(xb_out)


def evaluate(model: dict, df: pd.DataFrame) -> dict:
    att = df[df["attempt"] == 1]
    p = predict_make(model, att)
    y = att["made"].to_numpy()
    kick = att["yards_to_goal"] + 17
    by_kick = {}
    for label, lo, hi in (
        ("<30", 0, 29),
        ("30-39", 30, 39),
        ("40-49", 40, 49),
        ("50-54", 50, 54),
        ("55+", 55, 99),
    ):
        m = kick.between(lo, hi).to_numpy()
        if m.any():
            by_kick[label] = {
                "n": int(m.sum()),
                "pred": float(p[m].mean()),
                "obs": float(y[m].mean()),
            }
    non = df[df["attempt"] == 0]
    pn = predict_make(model, non)
    kick_non = non["yards_to_goal"] + 17
    counterfactual = {
        label: {"n": int(m.sum()), "pred_make_if_attempted": float(pn[m].mean())}
        for label, lo, hi in (
            ("30-39", 30, 39),
            ("40-49", 40, 49),
            ("50-54", 50, 54),
            ("55+", 55, 99),
        )
        if (m := kick_non.between(lo, hi).to_numpy()).any()
    }
    return {
        "overall": common.binary_metrics(y, p),
        "calibration": common.calibration_table(y, p),
        "by_kick_distance": by_kick,
        "non_attempts_counterfactual": counterfactual,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    df = build_frame()
    splits = common.split_by_season(df)
    LOG.info("attempts: %s", {k: int(v["attempt"].sum()) for k, v in splits.items()})

    variants = {}
    for with_sel in (True, False):
        m = fit(splits["train"], with_selection=with_sel)
        variants["heckman" if with_sel else "attempts_only"] = {
            "valid": evaluate(m, splits["valid"])["overall"],
            "mills_coef": m["outcome"]["coef"].get("mills_ratio"),
        }
    LOG.info("variants: %s", variants)

    # The selection correction is estimated at ~0 (see variants_valid), so the shipped model is
    # the attempts-only probit: same predictions, fewer inputs.
    holdout = fit(pd.concat([splits["train"], splits["valid"]]), with_selection=False)
    test_eval = evaluate(holdout, splits["test"])
    final = fit(df, with_selection=False)
    metadata = {
        "description": "P(field goal made) from yards_to_goal (kick distance ~ ytg + 17).",
        "method": (
            "Probit on attempts. The Heckman selection correction was fit and estimated at ~0 "
            "on the validation seasons, so it is not used. The season trend extrapolates at "
            "most one season past training."
        ),
        "scope": (
            f"fourth downs with yards_to_goal <= {MAX_YARDS_TO_GOAL}; blocked kicks are misses"
        ),
        "variants_valid": variants,
        "seasons": {
            "all": [TRAIN_SEASONS.start, TRAIN_SEASONS.stop - 1],
            "valid": VALID_SEASONS,
            "test": TEST_SEASONS,
        },
        "holdout_test": test_eval,
        "training_rows": {"fourth_downs": len(df), "attempts": int(df["attempt"].sum())},
        "selection_features": {"continuous": SELECTION_CONTINUOUS, "binary": SELECTION_BINARY},
        "outcome_features": {"continuous": OUTCOME_CONTINUOUS, "binary": OUTCOME_BINARY},
    }
    out = common.write_artifact(
        "field_goal", VERSION, {"coefficients.json": json.dumps(final, indent=2)}, metadata
    )
    LOG.info("wrote %s", out)
    print(
        json.dumps(
            {
                "variants_valid": variants,
                "test": test_eval["overall"],
                "by_kick_distance": test_eval["by_kick_distance"],
                "counterfactual": test_eval["non_attempts_counterfactual"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
