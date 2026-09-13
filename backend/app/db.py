"""SQLite storage for graded decisions, pregame snapshots, live outputs and run logs.

Tables follow docs/data-pipeline.md (games, plays_fourth_down, run_log) plus what grading,
live inference and the API need: teams, venues, game_sources (per-game processing status and
play-by-play hash), wp_series. Team and coach aggregates (phase 3) are not here yet.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from modeling.config import DATA_DIR

DB_PATH = DATA_DIR / "cfb4thdown.db"


def db_path() -> Path:
    """The SQLite file every job and the API use: CFB4THDOWN_DB if set (the Railway volume),
    else backend/data/cfb4thdown.db. Resolved per call so the environment always wins."""
    return Path(os.environ.get("CFB4THDOWN_DB") or DB_PATH)


SCHEMA_GAME_COLUMNS = (
    "game_id", "season", "week", "season_type", "start_date", "neutral_site", "home_id",
    "home_team", "home_classification", "home_conference", "home_points", "away_id",
    "away_team", "away_classification", "away_conference", "away_points", "is_final",
    "venue_id",
)  # fmt: skip

SCHEMA = """
CREATE TABLE IF NOT EXISTS run_log (
    run_id TEXT PRIMARY KEY,
    job TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    params TEXT,
    counts TEXT,
    errors TEXT,
    versions TEXT
);

CREATE TABLE IF NOT EXISTS games (
    game_id INTEGER PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    start_date TEXT,
    neutral_site INTEGER,
    home_id INTEGER NOT NULL,
    home_team TEXT,
    home_classification TEXT,
    home_conference TEXT,
    home_points INTEGER,
    away_id INTEGER NOT NULL,
    away_team TEXT,
    away_classification TEXT,
    away_conference TEXT,
    away_points INTEGER,
    is_final INTEGER,
    venue_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_games_week ON games(season, season_type, week);

CREATE TABLE IF NOT EXISTS plays_fourth_down (
    play_id TEXT PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    source TEXT NOT NULL,
    offense_id INTEGER NOT NULL,
    defense_id INTEGER NOT NULL,
    offense_classification TEXT,
    period INTEGER NOT NULL,
    clock_seconds REAL NOT NULL,
    clock_source TEXT,
    offense_score INTEGER NOT NULL,
    defense_score INTEGER NOT NULL,
    offense_timeouts INTEGER,
    defense_timeouts INTEGER,
    timeouts_imputed INTEGER,
    yards_to_goal INTEGER NOT NULL,
    distance INTEGER NOT NULL,
    pre_snap_wp REAL,
    decision TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    confidence TEXT,
    margin REAL,
    p_convert REAL,
    wp_go REAL,
    p_fg_make REAL,
    wp_field_goal REAL,
    punt_receiving_ytg REAL,
    wp_punt REAL,
    wp_actual REAL,
    wp_delta REAL,
    verdict TEXT NOT NULL,
    play_type TEXT,
    play_text TEXT,
    model_versions TEXT NOT NULL,
    run_id TEXT NOT NULL,
    graded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_p4_game ON plays_fourth_down(game_id);
CREATE INDEX IF NOT EXISTS idx_p4_season ON plays_fourth_down(season, season_type, week);
CREATE INDEX IF NOT EXISTS idx_p4_offense ON plays_fourth_down(offense_id, season);
CREATE INDEX IF NOT EXISTS idx_p4_situation ON plays_fourth_down(period, distance, yards_to_goal);

CREATE TABLE IF NOT EXISTS exclusions (
    play_id TEXT PRIMARY KEY,
    game_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    reason TEXT NOT NULL,
    run_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pregame_snapshots (
    game_id INTEGER NOT NULL,
    snapshot_at TEXT NOT NULL,
    season INTEGER NOT NULL,
    start_date TEXT,
    home_id INTEGER NOT NULL,
    away_id INTEGER NOT NULL,
    neutral_site INTEGER,
    home_elo REAL NOT NULL,
    away_elo REAL NOT NULL,
    home_spread REAL NOT NULL,
    spread_source TEXT NOT NULL,
    temperature REAL,
    wind_speed REAL,
    precipitation REAL,
    indoors INTEGER,
    elevation_m REAL,
    weather_source TEXT,
    elo_games_through TEXT,
    run_id TEXT NOT NULL,
    PRIMARY KEY (game_id, snapshot_at)
);

CREATE TABLE IF NOT EXISTS live_pending (
    game_id INTEGER PRIMARY KEY,
    polled_at TEXT NOT NULL,
    raw_snapshot TEXT NOT NULL,
    offense_id INTEGER,
    offense_source TEXT,
    state TEXT NOT NULL,
    recommendation TEXT,
    confidence TEXT,
    margin REAL,
    wp_go REAL,
    wp_field_goal REAL,
    wp_punt REAL,
    model_versions TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS live_decisions (
    espn_play_id TEXT PRIMARY KEY,
    game_id INTEGER NOT NULL,
    polled_at TEXT NOT NULL,
    raw_snapshot TEXT NOT NULL,
    offense_id INTEGER NOT NULL,
    period INTEGER NOT NULL,
    clock_seconds REAL NOT NULL,
    clock_source TEXT,
    offense_score INTEGER NOT NULL,
    defense_score INTEGER NOT NULL,
    yards_to_goal INTEGER NOT NULL,
    distance INTEGER NOT NULL,
    decision TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    confidence TEXT,
    margin REAL,
    wp_go REAL,
    wp_field_goal REAL,
    wp_punt REAL,
    wp_delta REAL,
    verdict TEXT NOT NULL,
    play_text TEXT,
    model_versions TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY,
    school TEXT NOT NULL,
    mascot TEXT,
    abbreviation TEXT,
    conference TEXT,
    classification TEXT,
    color TEXT,
    alt_color TEXT,
    logo_url TEXT,
    logo_dark_url TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS venues (
    venue_id INTEGER PRIMARY KEY,
    name TEXT,
    grass INTEGER,
    dome INTEGER,
    elevation_m REAL
);

-- One row per current-season game the process job has looked at. `status` says why a game is
-- or isn't graded; plays_sha256 detects play-by-play corrections inside the reprocessing window.
CREATE TABLE IF NOT EXISTS game_sources (
    game_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    plays_sha256 TEXT,
    play_rows INTEGER,
    first_processed_at TEXT,
    fetched_at TEXT NOT NULL,
    run_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wp_series (
    game_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    play_id TEXT NOT NULL,
    period INTEGER NOT NULL,
    clock_seconds REAL NOT NULL,
    down INTEGER NOT NULL,
    home_wp REAL NOT NULL,
    PRIMARY KEY (game_id, seq)
);
-- Live (ESPN) fourth downs matched to their batch (CFBD) grade (app/reconcile.py).
CREATE TABLE IF NOT EXISTS live_batch_links (
    espn_play_id TEXT PRIMARY KEY,
    cfbd_play_id TEXT,
    game_id INTEGER NOT NULL,
    clock_diff_seconds REAL,
    live_decision TEXT,
    batch_decision TEXT,
    live_recommendation TEXT,
    batch_recommendation TEXT,
    recommendation_agrees INTEGER,
    linked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_links_game ON live_batch_links(game_id);
CREATE INDEX IF NOT EXISTS idx_live_decisions_game ON live_decisions(game_id);

-- Coach attribution (jobs/coaches.py). One row per coach segment of a team-season.
CREATE TABLE IF NOT EXISTS coaches (
    coach_id INTEGER PRIMARY KEY,
    first_name TEXT,
    last_name TEXT,
    hire_date TEXT
);

CREATE TABLE IF NOT EXISTS coach_team_seasons (
    coach_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    segment INTEGER NOT NULL,
    games INTEGER NOT NULL,
    first_game_start TEXT,
    last_game_start TEXT,
    is_interim INTEGER NOT NULL,
    attribution TEXT NOT NULL,
    PRIMARY KEY (team_id, season, segment)
);
CREATE INDEX IF NOT EXISTS idx_cts_coach ON coach_team_seasons(coach_id);

CREATE TABLE IF NOT EXISTS coach_attribution_issues (
    team_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    reason TEXT NOT NULL,
    coaches INTEGER,
    PRIMARY KEY (team_id, season)
);

-- Optional manual commentary for Week in Review (plain text, paragraphs split on blank lines).
CREATE TABLE IF NOT EXISTS week_commentary (
    season INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    week INTEGER NOT NULL,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (season, season_type, week)
);
"""

# Columns added after a table first shipped; connect() adds them to older databases.
MIGRATIONS = {"games": {"venue_id": "INTEGER"}}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the API's read-only connections read while a job writes.
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        _migrate(conn)
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # created fresh by SCHEMA
        for column, kind in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def table_columns(table: str) -> list[str]:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


PRIMARY_KEYS = {
    "teams": ("team_id",),
    "venues": ("venue_id",),
    "game_sources": ("game_id",),
    "wp_series": ("game_id", "seq"),
    "live_batch_links": ("espn_play_id",),
    "coaches": ("coach_id",),
    "coach_team_seasons": ("team_id", "season", "segment"),
    "coach_attribution_issues": ("team_id", "season"),
    "week_commentary": ("season", "season_type", "week"),
    "games": ("game_id",),
    "plays_fourth_down": ("play_id",),
    "exclusions": ("play_id",),
    "pregame_snapshots": ("game_id", "snapshot_at"),
    "live_pending": ("game_id",),
    "live_decisions": ("espn_play_id",),
}


def start_run(conn: sqlite3.Connection, job: str, params: dict, versions: dict) -> str:
    run_id = f"{job}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    conn.execute(
        "INSERT INTO run_log (run_id, job, started_at, status, params, versions) "
        "VALUES (?,?,?,?,?,?)",
        (run_id, job, now_iso(), "running", json.dumps(params), json.dumps(versions)),
    )
    conn.commit()
    return run_id


def finish_run(
    conn: sqlite3.Connection, run_id: str, status: str, counts: dict, errors: list
) -> None:
    conn.execute(
        "UPDATE run_log SET finished_at=?, status=?, counts=?, errors=? WHERE run_id=?",
        (now_iso(), status, json.dumps(counts, default=int), json.dumps(errors), run_id),
    )


def replace_rows(
    conn: sqlite3.Connection, table: str, frame: pd.DataFrame, where: str, params: tuple
) -> None:
    """Delete rows matching `where`, then insert `frame` (column names must match the table)."""
    conn.execute(f"DELETE FROM {table} WHERE {where}", params)
    upsert_rows(conn, table, frame)


def _native(value: object) -> object:
    if (
        value is None
        or value is pd.NA
        or value is pd.NaT
        or (isinstance(value, float) and value != value)
    ):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalars
        return _native(value.item())
    return value


def upsert_rows(conn: sqlite3.Connection, table: str, frame: pd.DataFrame) -> None:
    """Insert rows; on primary-key conflict update the other columns in place.

    An in-place update (not INSERT OR REPLACE) keeps rows that reference this one valid.
    """
    if frame.empty:
        return
    cols = list(frame.columns)
    keys = PRIMARY_KEYS[table]
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
    sql = (
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
        f"ON CONFLICT({','.join(keys)}) DO UPDATE SET {updates}"
    )
    rows = [tuple(_native(v) for v in row) for row in frame.itertuples(index=False, name=None)]
    conn.executemany(sql, rows)
