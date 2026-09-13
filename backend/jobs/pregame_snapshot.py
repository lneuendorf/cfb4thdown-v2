"""Freeze pregame inputs for upcoming games: Elo, closing spread, weather forecast, venue.

    uv run python -m jobs.pregame_snapshot --season 2026 [--hours-ahead 36] [--include-started]

Live inference reads these snapshots; it never calls CFBD. Each run fetches fresh CFBD
games, lines and weather for the season (6 calls) into timestamped raw snapshots, replays
Elo through every final game that kicked off before each target, and writes one
pregame_snapshots row per target game.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from app import db, reference
from modeling import options
from modeling.build import elo
from modeling.build.games import COLUMNS as GAME_COLUMNS
from modeling.cfbd import CFBDClient, fetch_snapshot
from modeling.config import ARTIFACTS_DIR, SEASON_TYPES

LOG = logging.getLogger("pregame_snapshot")
BUILD_DIR = ARTIFACTS_DIR / "data_build"


def current_season_games(client: CFBDClient, season: int) -> pd.DataFrame:
    frames = []
    for season_type in SEASON_TYPES:
        rows, _ = fetch_snapshot(
            client, "games", {"year": season, "seasonType": season_type, "classification": "fbs"}
        )
        if rows:
            frames.append(pd.DataFrame(rows)[list(GAME_COLUMNS)].rename(columns=GAME_COLUMNS))
    g = pd.concat(frames, ignore_index=True).drop_duplicates("game_id")
    g["start_date"] = pd.to_datetime(g["start_date"], utc=True)
    for side in ("home", "away"):
        g[f"{side}_classification"] = g[f"{side}_classification"].fillna("unknown")
    g["is_final"] = (
        g["completed"].astype(bool) & g["home_points"].notna() & g["away_points"].notna()
    )
    return g


def spreads_from_lines(rows: list[dict]) -> pd.DataFrame:
    out = []
    for game in rows:
        spreads = [ln["spread"] for ln in game.get("lines", []) if ln.get("spread") is not None]
        out.append(
            {"game_id": game["id"], "home_spread": float(np.median(spreads)) if spreads else np.nan}
        )
    return pd.DataFrame(out, columns=["game_id", "home_spread"]).drop_duplicates("game_id")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--hours-ahead", type=float, default=36)
    parser.add_argument(
        "--include-started", action="store_true",
        help="also snapshot games already under way that have no snapshot (late start of the job)",
    )  # fmt: skip
    parser.add_argument(
        "--since",
        help="ISO time: snapshot every game that kicked off after this, final or not (replays)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run(args.season, args.hours_ahead, args.include_started, args.since)


def run(
    season: int,
    hours_ahead: float = 36,
    include_started: bool = False,
    since: str | None = None,
    game_ids: list[int] | None = None,
    client: CFBDClient | None = None,
    season_games: pd.DataFrame | None = None,
) -> dict:
    """Snapshot target games; returns run counts. `game_ids` snapshots exactly those games
    (used by jobs.process for final games that never got a pregame snapshot)."""
    client = client or CFBDClient()
    now = datetime.now(UTC)
    if season_games is None:
        season_games = current_season_games(client, season)
    with db.connect() as conn:
        history = reference.final_games_through(conn, season - 1)
        venues = reference.venues(conn)
    finals = pd.concat([history, season_games[season_games["is_final"]]], ignore_index=True)

    if game_ids is not None:
        upcoming = season_games["game_id"].isin(game_ids)
    else:
        horizon = pd.Timestamp(now + timedelta(hours=hours_ahead))
        upcoming = ~season_games["is_final"] & (season_games["start_date"] <= horizon)
        if not include_started:
            upcoming &= season_games["start_date"] >= pd.Timestamp(now)
        if since:
            # Ratings still come only from games that kicked off before each target.
            upcoming |= (season_games["start_date"] >= pd.Timestamp(since)) & (
                season_games["start_date"] <= horizon
            )
    targets = season_games[upcoming].copy()
    LOG.info("targets: %d games", len(targets))
    if targets.empty:
        return {"games": 0, "cfbd_calls": client.calls_made}

    params = elo.EloParams(**json.loads((BUILD_DIR / "elo.json").read_text())["params"])
    finals_before = finals[finals["start_date"] < targets["start_date"].max()]
    ratings = elo.ratings_before(finals_before, targets, params)

    lines = []
    weather = []
    for season_type in SEASON_TYPES:
        rows, _ = fetch_snapshot(client, "lines", {"year": season, "seasonType": season_type})
        lines += rows
        rows, _ = fetch_snapshot(
            client, "games/weather", {"year": season, "seasonType": season_type}
        )
        weather += rows
    spreads = spreads_from_lines(lines)
    weather_df = pd.DataFrame(weather).rename(
        columns={"id": "game_id", "gameIndoors": "game_indoors", "windSpeed": "wind_speed"}
    )
    defaults = options.assumptions()["weather_defaults"]
    imputer = json.loads((BUILD_DIR / "spread_imputer.json").read_text())

    snap = (
        targets.merge(ratings, on="game_id")
        .merge(spreads, on="game_id", how="left")
        .merge(
            weather_df[["game_id", "game_indoors", "temperature", "wind_speed", "precipitation"]]
            if not weather_df.empty
            else pd.DataFrame(
                columns=["game_id", "game_indoors", "temperature", "wind_speed", "precipitation"]
            ),
            on="game_id",
            how="left",
        )
        .merge(venues, on="venue_id", how="left")
    )
    home = (~snap["neutral_site"].astype(bool)).astype(float)
    imputed = (
        imputer["intercept"]
        + imputer["elo_diff"] * (snap["home_pregame_elo"] - snap["away_pregame_elo"])
        + imputer["home_field"] * home
    )
    indoors = (
        snap["game_indoors"]
        .astype("boolean")
        .fillna(snap["venue_dome"].astype("boolean"))
        .fillna(False)
    )
    has_weather = snap["temperature"].notna()
    run_versions = {"elo": params.__dict__, "decision_assumptions": options.ASSUMPTIONS_VERSION}
    with db.connect() as conn:
        params_log = {
            "season": season,
            "hours_ahead": hours_ahead,
            "include_started": include_started,
        }
        params_log.update({"since": since, "game_ids": game_ids})
        run_id = db.start_run(conn, "pregame_snapshot", params_log, run_versions)
        rows = pd.DataFrame(
            {
                "game_id": snap["game_id"],
                "snapshot_at": now.isoformat(),
                "season": snap["season"],
                "start_date": snap["start_date"].map(lambda t: t.isoformat()),
                "home_id": snap["home_id"],
                "away_id": snap["away_id"],
                "neutral_site": snap["neutral_site"].astype(bool).astype(int),
                "home_elo": snap["home_pregame_elo"],
                "away_elo": snap["away_pregame_elo"],
                "home_spread": snap["home_spread"].fillna(imputed),
                "spread_source": np.where(
                    snap["home_spread"].notna(), "cfbd_lines_median", "elo_imputed"
                ),
                "temperature": np.where(
                    indoors, 70.0, snap["temperature"].fillna(defaults["temperature"])
                ),
                "wind_speed": np.where(
                    indoors, 0.0, snap["wind_speed"].fillna(defaults["wind_speed"])
                ),
                "precipitation": np.where(
                    indoors, 0.0, snap["precipitation"].fillna(defaults["precipitation"])
                ),
                "indoors": indoors.astype(int),
                "elevation_m": snap["elevation_m"].fillna(defaults["elevation_m"]),
                "weather_source": np.where(has_weather, "cfbd_weather", "training_default"),
                "elo_games_through": finals_before["start_date"].max().isoformat(),
                "run_id": run_id,
            }
        )
        db.upsert_rows(conn, "pregame_snapshots", rows)
        counts = {
            "games": len(rows),
            "spread_imputed": int((rows["spread_source"] == "elo_imputed").sum()),
            "weather_default": int((rows["weather_source"] == "training_default").sum()),
            "cfbd_calls": client.calls_made,
            "cfbd_remaining": client.last_remaining,
        }
        db.finish_run(conn, run_id, "ok", counts, [])
    LOG.info(
        "snapshotted %d games (calls %d, remaining %s)",
        len(rows),
        client.calls_made,
        client.last_remaining,
    )

    return counts


if __name__ == "__main__":
    main()
