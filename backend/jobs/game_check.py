"""Decide whether anything else needs to run. Cheap: one ESPN request, no CFBD calls.

    uv run python -m jobs.game_check

Reads the FBS scoreboard for the last REPROCESS_WINDOW_DAYS + 1 days through tomorrow and
compares it with the database. Outputs (stdout JSON, and $GITHUB_OUTPUT when set):

    season           ESPN's season year
    has_new_games    a final game that isn't graded yet (awaiting_plays games are retried
                     at most every AWAITING_RETRY_HOURS, to spare the CFBD quota)
    has_live_games   a game is in progress
    pregame_due      a game kicks off within PREGAME_LEAD_HOURS without a recent snapshot
    reprocess_due    the daily reprocessing slot, with final games inside the window
    new_game_ids     the final games that triggered has_new_games

ESPN, not CFBD, is the cheap source here (docs/models.md: CFBD budget). CFBD and ESPN share
game ids, so no mapping is needed.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

import pandas as pd

from app import db
from jobs.process import DONE_STATUSES, REPROCESS_WINDOW_DAYS
from providers import espn

LOG = logging.getLogger("game_check")
AWAITING_RETRY_HOURS = 2
PREGAME_LEAD_HOURS = 3
# A snapshot taken this long before kickoff is recent enough (lines and forecasts settle late).
PREGAME_FRESH_HOURS = 12
REPROCESS_HOUR_UTC = 10  # 05:00 CT, after the overnight corrections


@dataclass
class CheckResult:
    season: int | None = None
    has_new_games: bool = False
    has_live_games: bool = False
    pregame_due: bool = False
    reprocess_due: bool = False
    new_game_ids: list[int] = field(default_factory=list)
    counts: dict = field(default_factory=dict)


def evaluate(board: dict, conn: sqlite3.Connection, now: datetime) -> CheckResult:
    games = espn.parse_scoreboard(board)
    starts = {int(e["id"]): pd.Timestamp(e["date"]) for e in board.get("events", [])}
    leagues = board.get("leagues") or [{}]
    season = (board.get("season") or leagues[0].get("season") or {}).get("year")
    sources = pd.read_sql_query("SELECT game_id, status, fetched_at FROM game_sources", conn)
    sources = sources.set_index("game_id")
    snaps = pd.read_sql_query(
        "SELECT game_id, MAX(snapshot_at) AS last FROM pregame_snapshots GROUP BY game_id", conn
    ).set_index("game_id")

    result = CheckResult(season=int(season) if season else None)
    retry_cutoff = now - timedelta(hours=AWAITING_RETRY_HOURS)
    window_start = pd.Timestamp(now - timedelta(days=REPROCESS_WINDOW_DAYS))
    finals_in_window = 0
    for g in games:
        start = starts.get(g.game_id)
        if g.state == "in":
            result.has_live_games = True
        elif g.state == "post":
            if start is not None and start >= window_start:
                finals_in_window += 1
            if g.game_id in sources.index:
                row = sources.loc[g.game_id]
                if row["status"] in DONE_STATUSES:
                    continue
                if pd.Timestamp(row["fetched_at"]) > pd.Timestamp(retry_cutoff):
                    continue
            result.new_game_ids.append(g.game_id)
        elif g.state == "pre" and start is not None:
            lead = start - pd.Timestamp(now)
            if timedelta(0) <= lead <= timedelta(hours=PREGAME_LEAD_HOURS):
                last = snaps["last"].get(g.game_id) if g.game_id in snaps.index else None
                fresh = last is not None and pd.Timestamp(last) >= start - timedelta(
                    hours=PREGAME_FRESH_HOURS
                )
                if not fresh:
                    result.pregame_due = True
    result.has_new_games = bool(result.new_game_ids)
    result.reprocess_due = now.hour == REPROCESS_HOUR_UTC and finals_in_window > 0
    result.counts = {
        "games": len(games),
        "live": sum(g.state == "in" for g in games),
        "final": sum(g.state == "post" for g in games),
        "finals_in_window": finals_in_window,
        "new_finals": len(result.new_game_ids),
    }
    return result


def run(now: datetime | None = None) -> CheckResult:
    now = now or datetime.now(UTC)
    start = (now - timedelta(days=REPROCESS_WINDOW_DAYS + 1)).strftime("%Y%m%d")
    end = (now + timedelta(days=1)).strftime("%Y%m%d")
    with db.connect() as conn:
        run_id = db.start_run(conn, "game_check", {"dates": f"{start}-{end}"}, {})
        try:
            board = espn.fetch_scoreboard_unstored(f"{start}-{end}")
        except espn.ESPNError as exc:
            db.finish_run(conn, run_id, "failed", {}, [repr(exc)])
            raise
        result = evaluate(board, conn, now)
        summary = asdict(result)
        summary["new_game_ids"] = len(result.new_game_ids)
        db.finish_run(conn, run_id, "ok", summary, [])
    _write_github_output(result)
    return result


def _write_github_output(result: CheckResult) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a") as f:
        for key in ("has_new_games", "has_live_games", "pregame_due", "reprocess_due"):
            f.write(f"{key}={'true' if getattr(result, key) else 'false'}\n")
        f.write(f"season={result.season or ''}\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print(json.dumps(asdict(run()), default=str))


if __name__ == "__main__":
    main()
