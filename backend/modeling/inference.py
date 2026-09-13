"""Load trained artifacts and predict from canonical pre-snap states.

Depends only on the artifact files (XGBoost JSON and coefficient JSON), numpy, pandas, scipy
and xgboost. No training code, no pickles. Inputs are canonical states as documented in
modeling.features; derived features are always recomputed here via add_state_features.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import norm

from modeling.config import ARTIFACTS_DIR
from modeling.features import add_state_features

MODEL_VERSIONS = {
    "win_probability": "2.0.0",
    "conversion": "2.0.0",
    "field_goal": "2.0.0",
    "punt": "2.0.0",
}


@dataclass(frozen=True)
class Artifact:
    name: str
    version: str
    path: Path
    metadata: dict


@cache
def artifact(name: str, version: str | None = None) -> Artifact:
    version = version or MODEL_VERSIONS[name]
    path = ARTIFACTS_DIR / name / version
    metadata = json.loads((path / "metadata.json").read_text())
    return Artifact(name, version, path, metadata)


@cache
def _booster(name: str, version: str | None = None) -> xgb.Booster:
    a = artifact(name, version)
    booster = xgb.Booster()
    booster.load_model(str(a.path / "model.json"))
    return booster


def _predict_xgb(name: str, frame: pd.DataFrame) -> np.ndarray:
    features = artifact(name).metadata["features"]
    missing = [f for f in features if f not in frame.columns]
    if missing:
        raise KeyError(f"{name} needs columns {missing}")
    return _booster(name).predict(xgb.DMatrix(frame[features]))


def win_probability(state: pd.DataFrame) -> np.ndarray:
    """P(offense wins) for canonical pre-snap states (regulation only)."""
    return _predict_xgb("win_probability", add_state_features(state))


def conversion_probability(state: pd.DataFrame) -> np.ndarray:
    """P(a fourth-down attempt converts). State must be down 4."""
    return _predict_xgb("conversion", add_state_features(state))


def punt_receiving_yards_to_goal(state: pd.DataFrame) -> np.ndarray:
    """Expected receiving-team yards_to_goal on its next snap after a punt."""
    return np.clip(_predict_xgb("punt", add_state_features(state)), 0, 99)


@cache
def _fg_coefficients() -> dict:
    return json.loads((artifact("field_goal").path / "coefficients.json").read_text())


def field_goal_make_probability(state: pd.DataFrame) -> np.ndarray:
    """P(field goal made) from yards_to_goal plus kick context.

    Extra columns required beyond the canonical state: season, wind_speed, precipitation,
    elevation_m, indoors. The season trend is clamped to the range stored with the model.
    """
    model = _fg_coefficients()
    stage = model["outcome"]
    df = add_state_features(state)
    lo, hi = stage["season_clamp"]
    values = {
        **{c: df[c].to_numpy(dtype=float) for c in stage["scale"] if c in df.columns},
        "yards_to_goal_sq": df["yards_to_goal"].to_numpy(dtype=float) ** 2,
        "season": np.clip(df["season"].to_numpy(dtype=float), lo, hi),
    }
    xb = np.full(len(df), stage["coef"]["const"])
    for col, s in stage["scale"].items():
        xb += stage["coef"][col] * (values[col] - s["mean"]) / s["std"]
    for col in stage["binary"]:
        xb += stage["coef"][col] * df[col].to_numpy(dtype=float)
    if model["with_selection"]:
        raise NotImplementedError("shipped field goal model does not use the selection stage")
    return norm.cdf(xb)
