"""Shared training utilities: data assembly, temporal splits, tuning, metrics, artifacts."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost as xgb

from modeling.config import (
    ARTIFACTS_DIR,
    PROCESSED_DIR,
    RANDOM_SEED,
    TEST_SEASONS,
    TRAIN_SEASONS,
    VALID_SEASONS,
)
from modeling.features import add_state_features

GAME_COLUMNS = [
    "game_id", "season", "week", "season_type", "start_date", "neutral_site",
    "home_id", "away_id", "home_points", "away_points",
    "home_pregame_elo", "away_pregame_elo", "home_spread_filled", "spread_imputed",
    "venue_id", "game_indoors", "temperature", "wind_speed", "precipitation",
    "grass", "venue_dome", "elevation_m",
]  # fmt: skip


def load_games() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / "games.parquet", columns=GAME_COLUMNS)


def load_plays(columns: list[str] | None = None) -> pd.DataFrame:
    frames = [
        pd.read_parquet(PROCESSED_DIR / "plays" / f"{s}.parquet", columns=columns)
        for s in TRAIN_SEASONS
    ]
    return pd.concat(frames, ignore_index=True)


def to_canonical_state(plays: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Join game context and express everything from the offense's perspective."""
    df = plays.merge(games, on="game_id", how="inner")
    home = df["offense_is_home"].to_numpy()
    df["home_indicator"] = np.where(df["neutral_site"].astype(bool), 0, np.where(home, 1, -1))
    df["offense_elo"] = np.where(home, df["home_pregame_elo"], df["away_pregame_elo"])
    df["defense_elo"] = np.where(home, df["away_pregame_elo"], df["home_pregame_elo"])
    df["offense_spread"] = np.where(home, df["home_spread_filled"], -df["home_spread_filled"])
    off_final = np.where(home, df["home_points"], df["away_points"])
    def_final = np.where(home, df["away_points"], df["home_points"])
    df["offense_final_margin"] = off_final - def_final
    return add_state_features(df)


def split_by_season(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "train": df[~df["season"].isin(VALID_SEASONS + TEST_SEASONS)],
        "valid": df[df["season"].isin(VALID_SEASONS)],
        "test": df[df["season"].isin(TEST_SEASONS)],
    }


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-7, 1 - 1e-7)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def binary_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    bins = np.clip((p * 20).astype(int), 0, 19)
    frame = pd.DataFrame({"y": y, "p": p, "bin": bins})
    cal = frame.groupby("bin").agg(pred=("p", "mean"), obs=("y", "mean"), n=("y", "size"))
    ece = float((cal["n"] * (cal["pred"] - cal["obs"]).abs()).sum() / len(frame))
    return {
        "n": int(len(y)),
        "log_loss": log_loss(y, p),
        "brier": float(np.mean((p - y) ** 2)),
        "ece_20bin": ece,
        "base_rate": float(np.mean(y)),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    b = np.clip((p * bins).astype(int), 0, bins - 1)
    frame = pd.DataFrame({"y": y, "p": p, "bin": b})
    cal = frame.groupby("bin").agg(pred=("p", "mean"), obs=("y", "mean"), n=("y", "size"))
    return [
        {
            "bin": int(i),
            "pred": round(float(r.pred), 4),
            "obs": round(float(r.obs), 4),
            "n": int(r.n),
        }
        for i, r in cal.iterrows()
    ]


@dataclass
class TuneResult:
    params: dict
    best_rounds: int
    valid_score: float
    n_trials: int


def tune_xgb(
    dtrain: xgb.DMatrix,
    dvalid: xgb.DMatrix,
    base_params: dict,
    n_trials: int,
    max_rounds: int = 2000,
    eval_metric: str = "logloss",
    min_child_weight_range: tuple[float, float] = (1.0, 200.0),
    refine_eta: float | None = None,
) -> TuneResult:
    """Seeded TPE search; each trial early-stops on the validation seasons."""
    import optuna  # training-only dependency; grading imports this module without it

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial) -> float:
        params = {
            **base_params,
            "eval_metric": eval_metric,
            "eta": trial.suggest_float("eta", 0.02, 0.2, log=True),
            "max_depth": trial.suggest_int("max_depth", 3, 9),
            "min_child_weight": trial.suggest_float(
                "min_child_weight", *min_child_weight_range, log=True
            ),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "lambda": trial.suggest_float("lambda", 1e-3, 50, log=True),
            "alpha": trial.suggest_float("alpha", 1e-3, 10, log=True),
            "gamma": trial.suggest_float("gamma", 1e-4, 5, log=True),
        }
        booster = xgb.train(
            params,
            dtrain,
            num_boost_round=max_rounds,
            evals=[(dvalid, "valid")],
            early_stopping_rounds=50,
            verbose_eval=False,
        )
        trial.set_user_attr("best_rounds", booster.best_iteration + 1)
        return float(booster.best_score)

    study = optuna.create_study(
        direction="minimize", sampler=optuna.samplers.TPESampler(seed=RANDOM_SEED)
    )
    study.optimize(objective, n_trials=n_trials)
    best = study.best_trial
    params = {**base_params, "eval_metric": eval_metric, **best.params}
    if refine_eta is None:
        return TuneResult(params, int(best.user_attrs["best_rounds"]), float(best.value), n_trials)
    # Keep the tuned tree structure, lower the learning rate, re-pick rounds on validation.
    params["eta"] = refine_eta
    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=20000,
        evals=[(dvalid, "valid")],
        early_stopping_rounds=100,
        verbose_eval=False,
    )
    return TuneResult(params, booster.best_iteration + 1, float(booster.best_score), n_trials)


def dataset_fingerprint(df: pd.DataFrame, columns: list[str]) -> str:
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df[columns], index=False).to_numpy().tobytes())
    return h.hexdigest()[:16]


def write_artifact(name: str, version: str, files: dict[str, bytes | str], metadata: dict) -> Path:
    out = ARTIFACTS_DIR / name / version
    out.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(out / filename, mode) as f:
            f.write(content)
    metadata = {
        **metadata,
        "model": name,
        "version": version,
        "trained_at": datetime.now(UTC).isoformat(),
        "libraries": {
            "python": platform.python_version(),
            "xgboost": xgb.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scikit-learn": sklearn.__version__,
        },
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))
    return out
