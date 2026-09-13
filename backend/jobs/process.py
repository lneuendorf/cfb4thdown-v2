"""Grade current-season games: new finals, and corrections inside the reprocessing window.

    uv run python -m jobs.process --season 2026                     # new final games only
    uv run python -m jobs.process --season 2026 --reprocess-window  # + re-check the last 7 days
    uv run python -m jobs.process --season 2026 --game-ids 401856671 401856783

Steps (docs/data-pipeline.md):
1. Fetch the season's games (2 CFBD calls) into timestamped snapshots; upsert `games`.
2. Targets: final games never graded, plus (with --reprocess-window) finals that kicked off in
   the last REPROCESS_WINDOW_DAYS.
3. Fetch play-by-play once per affected (season type, week) (1 call each).
4. Hash each game's plays. An unchanged hash for an already-processed game is skipped.
5. Games with plays but no pregame snapshot get one now (4-6 calls, jobs.pregame_snapshot).
6. Build pre-snap states, grade fourth downs and compute the WP series with the same code
   as the backfill (app.batch), then replace that game's rows in one transaction.

`game_sources.status` records the outcome per game: graded, failed_quality_gate (graded
nothing, the play-by-play doesn't reconcile with the final score), or awaiting_plays (CFBD
hasn't published play-by-play yet; retried on the next run). Failures are per game.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta

import pandas as pd

from app import batch, db, reconcile
from app import decisions as pipeline
from jobs import pregame_snapshot
from modeling import options
from modeling.build import plays as build_plays
from modeling.cfbd import CFBDClient, fetch_snapshot
from modeling.config import ARTIFACTS_DIR
from modeling.train.common import GAME_COLUMNS

LOG = logging.getLogger("process")
BUILD_DIR = ARTIFACTS_DIR / "data_build"
REPROCESS_WINDOW_DAYS = 7
DONE_STATUSES = ("graded", "failed_quality_gate")


def plays_hash(rows: list[dict]) -> str:
    ordered = sorted(rows, key=lambda r: str(r.get("id")))
    return hashlib.sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest()


def select_targets(
    season_games: pd.DataFrame,
    sources: pd.DataFrame,
    now: datetime,
    reprocess_window: bool,
    game_ids: list[int] | None,
) -> pd.DataFrame:
    finals = season_games[season_games["is_final"]]
    if game_ids:
        return finals[finals["game_id"].isin(game_ids)]
    done = set(sources.loc[sources["status"].isin(DONE_STATUSES), "game_id"])
    wanted = ~finals["game_id"].isin(done)
    if reprocess_window:
        cutoff = pd.Timestamp(now - timedelta(days=REPROCESS_WINDOW_DAYS))
        wanted |= finals["start_date"] >= cutoff
    return finals[wanted]


def game_context(season_games: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    """Current-season games in the GAME_COLUMNS shape the grading code expects."""
    latest = snapshots.sort_values("snapshot_at").drop_duplicates("game_id", keep="last")
    df = season_games.merge(latest, on="game_id", how="inner", suffixes=("", "_snap"))
    ctx = pd.DataFrame(
        {
            "game_id": df["game_id"],
            "season": df["season"],
            "week": df["week"],
            "season_type": df["season_type"],
            "start_date": df["start_date"],
            "neutral_site": df["neutral_site"].astype(bool),
            "home_id": df["home_id"],
            "away_id": df["away_id"],
            "home_points": df["home_points"],
            "away_points": df["away_points"],
            "home_pregame_elo": df["home_elo"],
            "away_pregame_elo": df["away_elo"],
            "home_spread_filled": df["home_spread"],
            "spread_imputed": df["spread_source"] == "elo_imputed",
            "venue_id": df["venue_id"],
            "game_indoors": df["indoors"].astype(bool),
            "temperature": df["temperature"],
            "wind_speed": df["wind_speed"],
            "precipitation": df["precipitation"],
            "grass": False,  # not a model input
            "venue_dome": df["indoors"].astype(bool),
            "elevation_m": df["elevation_m"],
        }
    )
    return ctx[GAME_COLUMNS]


def run(
    season: int,
    reprocess_window: bool = False,
    game_ids: list[int] | None = None,
    client: CFBDClient | None = None,
) -> dict:
    client = client or CFBDClient()
    now = datetime.now(UTC)
    season_games = pregame_snapshot.current_season_games(client, season)
    counts: dict = {
        "season_games": len(season_games),
        "final_games": int(season_games["is_final"].sum()),
    }
    errors: list[str] = []
    params_log = {"season": season, "reprocess_window": reprocess_window, "game_ids": game_ids}

    with db.connect() as conn:
        run_id = db.start_run(conn, "process", params_log, pipeline.model_versions())
        db.upsert_rows(conn, "games", _game_rows(season_games))
        conn.commit()
        sources = pd.read_sql_query("SELECT * FROM game_sources", conn)
        targets = select_targets(season_games, sources, now, reprocess_window, game_ids)
        counts["targets"] = len(targets)
        LOG.info("targets: %d of %d final games", len(targets), counts["final_games"])

        rows_by_game: dict[int, list[dict]] = {}
        weeks = targets[["season_type", "week"]].drop_duplicates().itertuples(index=False)
        for season_type, week in weeks:
            params = {
                "year": season,
                "week": int(week),
                "seasonType": season_type,
                "classification": "fbs",
            }
            week_rows, _ = fetch_snapshot(client, "plays", params)
            for r in week_rows:
                rows_by_game.setdefault(int(r["gameId"]), []).append(r)
        counts["weeks_fetched"] = len(targets[["season_type", "week"]].drop_duplicates())

        known = sources.set_index("game_id")
        changed: dict[int, str] = {}
        statuses: dict[str, int] = {}
        for game_id in targets["game_id"]:
            rows = rows_by_game.get(int(game_id), [])
            if not rows:
                _set_source(conn, known, int(game_id), "awaiting_plays", None, 0, run_id)
                statuses["awaiting_plays"] = statuses.get("awaiting_plays", 0) + 1
                continue
            digest = plays_hash(rows)
            prior = known.loc[game_id] if game_id in known.index else None
            if (
                prior is not None
                and prior["plays_sha256"] == digest
                and prior["status"] in DONE_STATUSES
            ):
                statuses["unchanged"] = statuses.get("unchanged", 0) + 1
                continue
            changed[int(game_id)] = digest
        conn.commit()

        if changed:
            snapshots = pd.read_sql_query("SELECT * FROM pregame_snapshots", conn)
            missing = sorted(set(changed) - set(snapshots["game_id"]))
            if missing:
                LOG.info("pregame snapshots missing for %d games; taking them now", len(missing))
                counts["pregame_snapshots_taken"] = pregame_snapshot.run(
                    season, game_ids=missing, client=client, season_games=season_games
                )["games"]
                snapshots = pd.read_sql_query("SELECT * FROM pregame_snapshots", conn)
            games_ctx = game_context(season_games[season_games["game_id"].isin(changed)], snapshots)
            no_context = sorted(set(changed) - set(games_ctx["game_id"]))
            for game_id in no_context:
                errors.append(f"{game_id}: no pregame context")
                changed.pop(game_id)
            if changed:
                graded_counts = _grade(
                    conn, season, season_games, games_ctx, rows_by_game, changed, known, run_id
                )
                for k, v in graded_counts.pop("statuses").items():
                    statuses[k] = statuses.get(k, 0) + v
                counts.update(graded_counts)
        counts["statuses"] = statuses
        counts["cfbd_calls"] = client.calls_made
        counts["cfbd_remaining"] = client.last_remaining
        db.finish_run(conn, run_id, "failed" if errors else "ok", counts, errors)
    LOG.info("process done: %s errors=%s", counts, errors)
    return counts


def _grade(conn, season, season_games, games_ctx, rows_by_game, changed, known, run_id) -> dict:
    durations = json.loads((BUILD_DIR / "play_durations.json").read_text())["median_seconds"]
    weights = json.loads((BUILD_DIR / "clock_interpolation_weights.json").read_text())[
        "median_seconds_to_next_play"
    ]
    raw = build_plays.raw_plays_frame([r for g in changed for r in rows_by_game[g]])
    build_games = season_games[season_games["game_id"].isin(changed)]
    plays, stats = build_plays.build_season(season, build_games, durations, weights, raw=raw)
    plays = plays[batch.PLAY_COLUMNS]
    classifications = build_games.set_index("game_id")[
        ["home_classification", "away_classification"]
    ]
    weather_defaults = options.assumptions()["weather_defaults"]
    graded, exclusions, grade_counts = batch.grade_plays(
        plays, games_ctx, classifications, weather_defaults, run_id, season
    )
    series = batch.wp_series(plays, games_ctx, weather_defaults)
    eligible = plays.groupby("game_id")["training_eligible_game"].first()

    ids = list(changed)
    marks = ",".join("?" for _ in ids)
    for table in ("plays_fourth_down", "exclusions", "wp_series"):
        conn.execute(f"DELETE FROM {table} WHERE game_id IN ({marks})", ids)
    db.upsert_rows(conn, "plays_fourth_down", graded)
    db.upsert_rows(conn, "exclusions", exclusions)
    db.upsert_rows(conn, "wp_series", series)
    statuses: dict[str, int] = {}
    for game_id, digest in changed.items():
        status = "graded" if bool(eligible.get(game_id, False)) else "failed_quality_gate"
        n_rows = len(rows_by_game[game_id])
        _set_source(conn, known, game_id, status, digest, n_rows, run_id)
        statuses[status] = statuses.get(status, 0) + 1
    conn.commit()
    reconciliation = reconcile.reconcile(conn, ids)
    conn.commit()
    return {
        "reconciliation": reconciliation,
        "games_graded": len(changed),
        "build": stats.counts,
        "grading": grade_counts,
        "wp_series_points": len(series),
        "flags": batch.validate(f"{season} process", graded),
        "statuses": statuses,
    }


def _set_source(conn, known, game_id, status, digest, n_rows, run_id) -> None:
    now = db.now_iso()
    first = None
    if game_id in known.index:
        first = known.loc[game_id, "first_processed_at"]
    if status in DONE_STATUSES and not first:
        first = now
    db.upsert_rows(
        conn,
        "game_sources",
        pd.DataFrame(
            [
                {
                    "game_id": game_id,
                    "status": status,
                    "plays_sha256": digest,
                    "play_rows": n_rows,
                    "first_processed_at": first,
                    "fetched_at": now,
                    "run_id": run_id,
                }
            ]
        ),
    )


def _game_rows(season_games: pd.DataFrame) -> pd.DataFrame:
    rows = season_games[[c for c in db.SCHEMA_GAME_COLUMNS if c in season_games.columns]].copy()
    rows["start_date"] = rows["start_date"].map(lambda t: t.isoformat())
    rows["is_final"] = rows["is_final"].astype(int)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--reprocess-window", action="store_true")
    parser.add_argument("--game-ids", type=int, nargs="*")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run(args.season, args.reprocess_window, args.game_ids)


if __name__ == "__main__":
    main()
