"""Grade every in-scope fourth down for a season range into SQLite.

    uv run python -m jobs.backfill --from 2013 --to 2025

Reads the processed tables built from the raw cache (no API calls). Each season is replaced
atomically: its graded rows, exclusions and WP series are deleted and rewritten in one
transaction, and the run is recorded in run_log with exclusion counts by reason. Every game
since ELO_FIRST_SEASON and the venue table are also written, so jobs that replay Elo or need
venues (pregame_snapshot, process) can run from the database alone.

Grades for seasons the models were trained on are in-sample; docs/grades.md says so.
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from app import batch, db
from app import decisions as pipeline
from modeling.build import context
from modeling.build.games import load_games
from modeling.config import ELO_FIRST_SEASON, PROCESSED_DIR
from modeling.train import common, decisions

LOG = logging.getLogger("backfill")
model_versions = pipeline.model_versions


def game_rows(games_all: pd.DataFrame) -> pd.DataFrame:
    rows = games_all[[c for c in db.SCHEMA_GAME_COLUMNS if c in games_all.columns]].copy()
    rows["start_date"] = rows["start_date"].map(lambda t: t.isoformat())
    return rows


def venue_rows() -> pd.DataFrame:
    v = context.load_venues()
    return pd.DataFrame(
        {
            "venue_id": v["venue_id"],
            "grass": v["grass"].astype("boolean").astype("Int64"),
            "dome": v["venue_dome"].astype("boolean").astype("Int64"),
            "elevation_m": v["elevation_m"],
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="first", type=int, default=2013)
    parser.add_argument("--to", dest="last", type=int, default=2025)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    games_all = pd.read_parquet(PROCESSED_DIR / "games.parquet")
    games = common.load_games()
    classifications = games_all.set_index("game_id")[["home_classification", "away_classification"]]
    weather_defaults = decisions.weather_defaults(games)
    weather_defaults["elevation_m"] = float(games["elevation_m"].median())

    with db.connect() as conn:
        run_id = db.start_run(
            conn, "backfill", {"from": args.first, "to": args.last}, model_versions()
        )
        all_counts, flags, errors = {}, [], []
        # Elo burn-in seasons aren't in the processed table; they come from the raw cache.
        burn_in = load_games(ELO_FIRST_SEASON, int(games_all["season"].min()) - 1)
        db.upsert_rows(conn, "games", game_rows(pd.concat([burn_in, games_all])))
        db.upsert_rows(conn, "venues", venue_rows())
        conn.commit()
        for season in range(args.first, args.last + 1):
            try:
                plays = pd.read_parquet(
                    PROCESSED_DIR / "plays" / f"{season}.parquet", columns=batch.PLAY_COLUMNS
                )
                graded, exclusions, counts = batch.grade_plays(
                    plays, games, classifications, weather_defaults, run_id, season
                )
                series = batch.wp_series(plays, games, weather_defaults)
                db.replace_rows(
                    conn, "plays_fourth_down", graded, "season = ? AND source = 'cfbd'", (season,)
                )
                db.replace_rows(conn, "exclusions", exclusions, "season = ?", (season,))
                db.replace_rows(
                    conn,
                    "wp_series",
                    series,
                    "game_id IN (SELECT game_id FROM games WHERE season = ?)",
                    (season,),
                )
                conn.commit()
                counts["wp_series_points"] = len(series)
                flags += batch.validate(str(season), graded)
                all_counts[season] = counts
                LOG.info(
                    "%d: graded %d; exclusions %s", season, counts["graded"], counts["exclusions"]
                )
            except Exception as exc:  # per-season failure, keep going
                conn.rollback()
                errors.append(f"{season}: {exc!r}")
                LOG.exception("season %d failed", season)
        db.finish_run(
            conn,
            run_id,
            "failed" if errors else "ok",
            {"seasons": all_counts, "flags": flags},
            errors,
        )
    LOG.info("run %s done; flags=%s errors=%s", run_id, flags, errors)


if __name__ == "__main__":
    main()
