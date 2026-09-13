"""In-process scheduler: the jobs in docs/automation.md, run inside the API service.

SQLite lives on the API host's disk, so the jobs that write it must run on that host. GitHub
Actions runners can't share the file (docs/automation.md, "Wiring", is superseded by this).

Two loops:
- ticker: ESPN FBS scoreboard (score-only) every TICKER_LIVE_SECONDS while games are live,
  every TICKER_IDLE_SECONDS otherwise. Held in memory for GET /ticker.
- jobs, checked every minute and run hourly at CHECK_MINUTE: jobs.game_check, then
  jobs.process when it reports new finals or the daily reprocessing slot, and
  jobs.pregame_snapshot when a kickoff is near. Mondays at TEAMS_HOUR_UTC (and
  on the first hourly check if no coach attribution exists yet): jobs.teams, then jobs.coaches.

Jobs run in a worker thread one at a time; a failing job is logged (run_log) and the loop
keeps going.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from providers import espn

LOG = logging.getLogger("scheduler")
TICKER_LIVE_SECONDS = 30
TICKER_IDLE_SECONDS = 600
TICKER_STALE_SECONDS = 180
CHECK_MINUTE = 5
TEAMS_HOUR_UTC = 9


class TickerCache:
    """Latest ESPN scores, shaped as the contract's ticker entries."""

    def __init__(self) -> None:
        self.games: list[dict] = []
        self.games_live = 0
        self.updated_at: str | None = None
        self._updated: datetime | None = None

    def update(self, board: dict) -> None:
        self.games = ticker_entries(board)
        self.games_live = sum(g["status"] == "live" for g in self.games)
        self._updated = datetime.now(UTC)
        self.updated_at = self._updated.strftime("%Y-%m-%dT%H:%M:%SZ")

    def is_stale(self) -> bool:
        if self._updated is None:
            return True
        limit = TICKER_STALE_SECONDS if self.games_live else TICKER_IDLE_SECONDS * 2
        return datetime.now(UTC) - self._updated > timedelta(seconds=limit)


def ticker_entries(board: dict) -> list[dict]:
    status = {"in": "live", "post": "final", "pre": "scheduled"}
    out = []
    for event in board.get("events", []):
        comp = event["competitions"][0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        state = event["status"]["type"]["state"]
        out.append(
            {
                "game_id": str(event["id"]),
                "away": sides["away"]["team"].get("abbreviation"),
                "away_score": int(sides["away"].get("score") or 0),
                "home": sides["home"]["team"].get("abbreviation"),
                "home_score": int(sides["home"].get("score") or 0),
                "status": status.get(state, state),
                "period": event["status"].get("period") or None,
                "clock": event["status"].get("displayClock") if state == "in" else None,
                "start_date": event.get("date"),
                # Live fourth-down grades arrive with live grading (docs/roadmap.md Phase 6).
                "wp_delta_last": None,
            }
        )
    order = {"live": 0, "final": 1, "scheduled": 2}
    return sorted(out, key=lambda g: (order.get(g["status"], 3), g["start_date"] or ""))


class Scheduler:
    def __init__(self, ticker: TickerCache) -> None:
        self.ticker = ticker
        self._tasks: list[asyncio.Task] = []
        self._last_check_hour: datetime | None = None
        self._last_teams_day: str | None = None

    def start(self) -> None:
        # Two independent loops, so a long process run never delays the ticker.
        self._tasks = [
            asyncio.create_task(self._forever(self._ticker_tick)),
            asyncio.create_task(self._forever(self._hourly_tick)),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()

    async def _forever(self, tick) -> None:
        while True:
            try:
                delay = await tick(datetime.now(UTC))
            except asyncio.CancelledError:
                raise
            except Exception:  # keep the loop alive; jobs log their own failures to run_log
                LOG.exception("scheduler tick failed")
                delay = 60
            await asyncio.sleep(delay)

    async def _ticker_tick(self, now: datetime) -> float:
        board = await asyncio.to_thread(espn.fetch_scoreboard_unstored, None, 1)
        self.ticker.update(board)
        return TICKER_LIVE_SECONDS if self.ticker.games_live else TICKER_IDLE_SECONDS

    async def _hourly_tick(self, now: datetime) -> float:
        await self._hourly(now)
        return 60 - datetime.now(UTC).second

    async def _hourly(self, now: datetime) -> None:
        hour = now.replace(minute=0, second=0, microsecond=0)
        if now.minute < CHECK_MINUTE or self._last_check_hour == hour:
            return
        self._last_check_hour = hour
        from jobs import coaches, game_check, pregame_snapshot, process, teams

        result = await asyncio.to_thread(game_check.run)
        LOG.info("game_check: %s", result.counts)
        if result.season and (result.has_new_games or result.reprocess_due):
            await asyncio.to_thread(process.run, result.season, result.reprocess_due)
        if result.season and result.pregame_due:
            await asyncio.to_thread(pregame_snapshot.run, result.season, 3.0, True)
        day = now.strftime("%Y-%m-%d")
        weekly = now.weekday() == 0 and now.hour == TEAMS_HOUR_UTC
        if (weekly or not await asyncio.to_thread(_has_coaches)) and self._last_teams_day != day:
            self._last_teams_day = day
            await asyncio.to_thread(teams.run)
            await asyncio.to_thread(coaches.run)


def _has_coaches() -> bool:
    from app import db

    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM coach_team_seasons LIMIT 1").fetchone() is not None
