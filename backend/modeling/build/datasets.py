"""Build processed game and play tables from the raw cache.

    uv run python -m modeling.build.datasets

Outputs (data/processed/):
    games.parquet               one row per in-scope game with pregame context
    plays/{season}.parquet      one row per play with the reconstructed pre-snap state
Fitted build parameters and data-quality counts go to modeling/artifacts/data_build/.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict

import numpy as np
import pandas as pd

from modeling.build import context, elo, plays, team_form
from modeling.build.games import load_games
from modeling.config import (
    ARTIFACTS_DIR,
    ELO_FIRST_SEASON,
    PROCESSED_DIR,
    TRAIN_SEASONS,
)

LOG = logging.getLogger("datasets")
BUILD_DIR = ARTIFACTS_DIR / "data_build"
# Seasons whose play text carries snap timestamps often enough to fit play durations.
DURATION_FIT_SEASONS = [2025]
# Seasons whose clocks mostly update every play; used to weight stale-clock interpolation.
INTERPOLATION_WEIGHT_SEASONS = [2024, 2025]
ELO_TUNE_SEASONS = range(2003, 2013)

PLAY_COLUMNS = [
    "game_id", "play_id", "drive_id", "drive_number", "play_number", "period", "half",
    "clock_raw", "clock_filled", "clock_interpolated", "clock_seconds", "clock_source",
    "clock_semantics",
    "offense_id", "defense_id", "offense_is_home",
    "offense_score", "defense_score", "offense_score_post", "defense_score_post",
    "offense_points_on_play", "defense_points_on_play",
    "offense_timeouts", "defense_timeouts", "timeouts_imputed", "timeouts_known",
    "score_reconciled", "score_consistency", "training_eligible_game",
    "home_score_post", "away_score_post",
    "yards_to_goal", "down", "distance", "distance_raw", "yards_gained",
    "play_type", "play_text", "category", "ppa", "valid_state",
    "next_offense_id", "next_yards_to_goal", "next_down", "next_half",
]  # fmt: skip


def build_games() -> tuple[pd.DataFrame, dict]:
    games = load_games(ELO_FIRST_SEASON, TRAIN_SEASONS[-1])
    final = games[games["is_final"]]
    params, grid = elo.tune(final, ELO_TUNE_SEASONS)
    pre = elo.run_elo(final, params)
    elo_report = {
        "params": asdict(params),
        "tuned_on_seasons": [ELO_TUNE_SEASONS.start, ELO_TUNE_SEASONS.stop - 1],
        "eval_2013_2025": elo.evaluate(final, pre, TRAIN_SEASONS),
        "grid": grid,
    }
    games = games.merge(pre, on="game_id", how="left")
    games = games[games["season"].isin(TRAIN_SEASONS)]

    games = games.merge(context.load_spreads(TRAIN_SEASONS), on="game_id", how="left")
    games = games.merge(context.load_weather(TRAIN_SEASONS), on="game_id", how="left")
    games = games.merge(context.load_venues(), on="venue_id", how="left")
    return games.reset_index(drop=True), elo_report


def fit_spread_imputer(games: pd.DataFrame) -> dict:
    """home_spread ~ elo_diff + home_field, least squares on games with a market spread."""
    ok = games["home_spread"].notna() & games["home_pregame_elo"].notna()
    x_elo = (games.loc[ok, "home_pregame_elo"] - games.loc[ok, "away_pregame_elo"]).to_numpy()
    x_home = (~games.loc[ok, "neutral_site"].astype(bool)).astype(float).to_numpy()
    X = np.column_stack([np.ones(ok.sum()), x_elo, x_home])
    coef, *_ = np.linalg.lstsq(X, games.loc[ok, "home_spread"].to_numpy(), rcond=None)
    resid = games.loc[ok, "home_spread"].to_numpy() - X @ coef
    return {
        "formula": "home_spread = intercept + elo_diff * (home_elo - away_elo) + home * home_field",
        "intercept": float(coef[0]),
        "elo_diff": float(coef[1]),
        "home_field": float(coef[2]),
        "n": int(ok.sum()),
        "mae": float(np.abs(resid).mean()),
    }


def apply_spread_imputer(games: pd.DataFrame, imputer: dict) -> pd.DataFrame:
    games = games.copy()
    est = (
        imputer["intercept"]
        + imputer["elo_diff"] * (games["home_pregame_elo"] - games["away_pregame_elo"])
        + imputer["home_field"] * (~games["neutral_site"].astype(bool)).astype(float)
    )
    games["spread_imputed"] = games["home_spread"].isna()
    games["home_spread_filled"] = games["home_spread"].fillna(est)
    return games


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (PROCESSED_DIR / "plays").mkdir(parents=True, exist_ok=True)

    games, elo_report = build_games()
    imputer = fit_spread_imputer(games[games["is_final"]])
    games = apply_spread_imputer(games, imputer)
    games.to_parquet(PROCESSED_DIR / "games.parquet", index=False)
    (BUILD_DIR / "elo.json").write_text(json.dumps(elo_report, indent=2))
    (BUILD_DIR / "spread_imputer.json").write_text(json.dumps(imputer, indent=2))
    LOG.info(
        "games: %d rows; elo %s; spread imputer MAE %.2f",
        len(games),
        elo_report["params"],
        imputer["mae"],
    )

    weight_frames = [
        plays.prepare_season(s, games, plays.BuildStats()) for s in INTERPOLATION_WEIGHT_SEASONS
    ]
    weights = plays.estimate_interpolation_weights(weight_frames)
    (BUILD_DIR / "clock_interpolation_weights.json").write_text(
        json.dumps(
            {"fit_seasons": INTERPOLATION_WEIGHT_SEASONS, "median_seconds_to_next_play": weights},
            indent=2,
        )
    )
    durations = plays.estimate_play_durations(DURATION_FIT_SEASONS, games, weights)
    (BUILD_DIR / "play_durations.json").write_text(
        json.dumps({"fit_seasons": DURATION_FIT_SEASONS, "median_seconds": durations}, indent=2)
    )

    quality = {}
    for season in TRAIN_SEASONS:
        df, stats = plays.build_season(season, games, durations, weights)
        df[PLAY_COLUMNS].to_parquet(PROCESSED_DIR / "plays" / f"{season}.parquet", index=False)
        quality[season] = stats.counts
        LOG.info("plays %d: %s", season, stats.counts)
    (BUILD_DIR / "play_quality.json").write_text(json.dumps(quality, indent=2))
    build_team_form(games)


def build_team_form(games: pd.DataFrame) -> None:
    """Weekly opponent-adjusted success rates (used in ablations; see docs/models.md D11)."""
    frames = [pd.read_parquet(PROCESSED_DIR / "plays" / f"{s}.parquet") for s in TRAIN_SEASONS]
    rates = team_form.team_game_rates(pd.concat(frames, ignore_index=True), games)
    team_form.weekly_ratings(rates, games).to_parquet(
        PROCESSED_DIR / "team_form.parquet", index=False
    )


if __name__ == "__main__":
    main()
