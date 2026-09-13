"""Batch grading shared by the historical backfill and the current-season process job.

Input is a processed play frame (modeling.build.plays.build_season output) and a game context
frame with the columns in modeling.train.common.GAME_COLUMNS. Historical seasons get context
from data/processed/games.parquet; the current season gets it from pregame_snapshots.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app import db
from app import decisions as pipeline
from modeling import inference, options
from modeling.train import common, decisions

PLAY_COLUMNS = [
    "game_id", "play_id", "period", "half", "clock_seconds", "clock_source", "offense_id",
    "defense_id", "offense_is_home", "offense_score", "defense_score", "offense_timeouts",
    "defense_timeouts", "timeouts_known", "yards_to_goal", "down", "distance", "play_type",
    "play_text", "category", "valid_state", "training_eligible_game",
]  # fmt: skip

OPTION_COLUMNS = (
    "p_convert",
    "wp_go",
    "p_fg_make",
    "wp_field_goal",
    "punt_receiving_ytg",
    "wp_punt",
)
WP_SERIES_MAX_POINTS = 200


def impute_timeouts(frame: pd.DataFrame) -> pd.DataFrame:
    """Median timeouts by half and minutes left in the half, for games that never recorded them."""
    lookup = options.assumptions()["timeouts_median_by_half_and_minutes_left"]
    frame = frame.copy()
    unknown = ~frame["timeouts_known"].astype(bool)
    left = np.where(frame["period"] <= 2, 2 - frame["period"], 4 - frame["period"]) * 900
    minutes = ((left + frame["clock_seconds"]) // 60).clip(upper=30).astype(int)
    keys = frame["half"].astype(int).astype(str) + "|" + minutes.astype(str)
    off = keys.map(lambda k: lookup.get(k, {"offense": 3})["offense"])
    dfn = keys.map(lambda k: lookup.get(k, {"defense": 3})["defense"])
    frame.loc[unknown, "offense_timeouts"] = off[unknown]
    frame.loc[unknown, "defense_timeouts"] = dfn[unknown]
    frame["timeouts_imputed"] = unknown
    return frame


def grade_plays(
    plays: pd.DataFrame,
    games: pd.DataFrame,
    classifications: pd.DataFrame,
    weather_defaults: dict,
    run_id: str,
    season: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Graded fourth downs, exclusions with reasons, and run counts for one batch of plays."""
    cand = plays[(plays["down"] == 4) & (plays["category"] != "non_state")].copy()
    reason = pd.Series(
        np.select(
            [cand["period"] > 4, ~cand["valid_state"], ~cand["training_eligible_game"]],
            ["overtime", "invalid_state", "game_failed_quality_gate"],
            default="",
        ),
        index=cand.index,
    )
    reason = reason.where(reason != "", pipeline.category_exclusion(cand["category"]))
    kept = impute_timeouts(cand[reason == ""])
    state = common.to_canonical_state(kept, games)
    state = decisions.apply_weather(state, weather_defaults)
    state["decision"] = pipeline.classify_decision(state["category"])
    state["pre_snap_wp"] = inference.win_probability(state) if len(state) else []
    late_reason = pipeline.model_scope_exclusion(state).to_numpy() if len(state) else np.array([])
    late_excluded = state[late_reason != ""]
    graded = state[late_reason == ""].reset_index(drop=True)
    out = _graded_frame(graded, classifications, run_id) if len(graded) else _empty_graded()

    exclusions = pd.concat(
        [
            cand.loc[reason != "", ["play_id", "game_id"]].assign(reason=reason[reason != ""]),
            late_excluded[["play_id", "game_id"]].assign(reason=late_reason[late_reason != ""]),
        ],
        ignore_index=True,
    ).assign(season=season, run_id=run_id)
    exclusions["play_id"] = exclusions["play_id"].astype(str)
    counts = {
        "fourth_down_candidates": len(cand),
        "graded": len(out),
        "timeouts_imputed": int(out["timeouts_imputed"].sum()) if len(out) else 0,
        "exclusions": exclusions["reason"].value_counts().to_dict(),
        "verdicts": out["verdict"].value_counts().to_dict() if len(out) else {},
    }
    return out, exclusions, counts


def _graded_frame(graded: pd.DataFrame, classifications: pd.DataFrame, run_id: str) -> pd.DataFrame:
    res = pipeline.grade_decisions(graded)
    home = graded["offense_is_home"].to_numpy()
    classification = np.where(
        home,
        graded["game_id"].map(classifications["home_classification"]),
        graded["game_id"].map(classifications["away_classification"]),
    )
    return pd.DataFrame(
        {
            "play_id": graded["play_id"].astype(str),
            "game_id": graded["game_id"],
            "season": graded["season"],
            "week": graded["week"],
            "season_type": graded["season_type"],
            "source": "cfbd",
            "offense_id": graded["offense_id"],
            "defense_id": graded["defense_id"],
            "offense_classification": classification,
            "period": graded["period"],
            "clock_seconds": graded["clock_seconds"],
            "clock_source": graded["clock_source"],
            "offense_score": graded["offense_score"].astype(int),
            "defense_score": graded["defense_score"].astype(int),
            "offense_timeouts": graded["offense_timeouts"].astype(int),
            "defense_timeouts": graded["defense_timeouts"].astype(int),
            "timeouts_imputed": graded["timeouts_imputed"].astype(int),
            "yards_to_goal": graded["yards_to_goal"].astype(int),
            "distance": graded["distance"].astype(int),
            "pre_snap_wp": graded["pre_snap_wp"],
            "decision": graded["decision"],
            **{c: res[c] for c in ("recommendation", "confidence", "margin")},
            **{c: res[c] for c in OPTION_COLUMNS},
            **{c: res[c] for c in ("wp_actual", "wp_delta", "verdict")},
            "play_type": graded["play_type"],
            "play_text": graded["play_text"],
            "model_versions": json.dumps(pipeline.model_versions()),
            "run_id": run_id,
            "graded_at": db.now_iso(),
        }
    )


def _empty_graded() -> pd.DataFrame:
    cols = db.table_columns("plays_fourth_down")
    return pd.DataFrame(columns=cols)


def wp_series(plays: pd.DataFrame, games: pd.DataFrame, weather_defaults: dict) -> pd.DataFrame:
    """Home-team WP before every valid snap (downs 1-4) in games that passed the quality gate.

    Downsampled to WP_SERIES_MAX_POINTS per game, always keeping fourth downs so chart markers
    sit on the line.
    """
    rows = plays[plays["valid_state"] & plays["training_eligible_game"]].copy()
    if rows.empty:
        return pd.DataFrame(
            columns=["game_id", "seq", "play_id", "period", "clock_seconds", "down", "home_wp"]
        )
    rows["seq"] = rows.groupby("game_id").cumcount()
    rows = impute_timeouts(rows)
    state = decisions.apply_weather(common.to_canonical_state(rows, games), weather_defaults)
    wp = inference.win_probability(state)
    home = state["offense_is_home"].astype(bool).to_numpy()
    series = pd.DataFrame(
        {
            "game_id": state["game_id"],
            "seq": state["seq"],
            "play_id": state["play_id"].astype(str),
            "period": state["period"].astype(int),
            "clock_seconds": state["clock_seconds"].astype(float),
            "down": state["down"].astype(int),
            "home_wp": np.round(np.where(home, wp, 1 - wp), 4),
        }
    ).sort_values(["game_id", "seq"])
    return pd.concat([_downsample(g) for _, g in series.groupby("game_id")], ignore_index=True)


def _downsample(game: pd.DataFrame) -> pd.DataFrame:
    if len(game) <= WP_SERIES_MAX_POINTS:
        return game
    keep = np.zeros(len(game), dtype=bool)
    keep[np.linspace(0, len(game) - 1, WP_SERIES_MAX_POINTS).round().astype(int)] = True
    keep |= (game["down"] == 4).to_numpy()
    return game[keep]


def validate(label: str, graded: pd.DataFrame) -> list[str]:
    """Checks from docs/data-pipeline.md; flag and continue."""
    flags = []
    if graded.empty:
        return flags
    per_game = graded.groupby("game_id").size()
    odd = per_game[(per_game < 2) | (per_game > 20)]
    if len(odd):
        flags.append(f"{label}: {len(odd)} games with graded fourth downs outside 2-20")
    wp = graded[["wp_go", "wp_field_goal", "wp_punt"]].to_numpy(dtype=float)
    if np.any((wp[~np.isnan(wp)] < 0) | (wp[~np.isnan(wp)] > 1)):
        flags.append(f"{label}: option WP outside [0, 1]")
    if (graded["wp_delta"].dropna() > 1e-9).any():
        flags.append(f"{label}: positive wp_delta")
    return flags
