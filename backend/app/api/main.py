"""FastAPI service (docs/api-contract.md). Base path /api/v1, JSON, freshness envelope.

    uv run uvicorn app.api.main:app --reload --port 8000

Environment:
    CFB4THDOWN_DB     SQLite path (default backend/data/cfb4thdown.db)
    CORS_ORIGINS      comma-separated origins allowed to call the API (default: none)
    SCHEDULER_ENABLED "1" to run game_check / process / pregame snapshots / ticker in-process
                      (app.scheduler). Needs CFBD_API_KEY. Run a single worker when enabled.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db
from app import decisions as pipeline
from app.api import aggregates, store
from app.scheduler import Scheduler, TickerCache

SeasonType = Literal["regular", "postseason"]

# Cache-Control per contract TTLs. Browsers revalidate quickly; a CDN may hold longer.
CACHE_SHORT = "public, max-age=30, s-maxage=60"
CACHE_WEEK = "public, max-age=300, s-maxage=3600"
CACHE_SETTLED = "public, max-age=3600, s-maxage=86400"
CACHE_TEAMS = "public, max-age=86400, s-maxage=604800"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


def db_path() -> Path:
    return Path(os.environ.get("CFB4THDOWN_DB", str(db.DB_PATH)))


def get_conn() -> Iterator[sqlite3.Connection]:
    path = db_path()
    if not path.exists():
        raise ApiError(503, "PIPELINE_COLD", "No data is available yet.")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def envelope(data: object, conn: sqlite3.Connection | None, source: str = "cache") -> dict:
    return {
        "data": data,
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stale": store.pipeline_stale(conn) if conn is not None else False,
            "source": source,
        },
    }


def create_app(scheduler_enabled: bool | None = None) -> FastAPI:
    if scheduler_enabled is None:
        scheduler_enabled = os.environ.get("SCHEDULER_ENABLED") == "1"
    ticker = TickerCache()
    scheduler = Scheduler(ticker) if scheduler_enabled else None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if scheduler:
            scheduler.start()
        yield
        if scheduler:
            await scheduler.stop()

    app = FastAPI(title="cfb4thdown API", version="1", lifespan=lifespan, docs_url="/api/v1/docs",
                  openapi_url="/api/v1/openapi.json")  # fmt: skip
    app.state.ticker = ticker
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"])

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, exc.status)

    @app.exception_handler(RequestValidationError)
    async def bad_params(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", [])[1:])
        message = f"Invalid parameter {where}: {first.get('msg', 'bad value')}."
        return JSONResponse({"error": {"code": "BAD_PARAMS", "message": message}}, 400)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "ERROR"
        return JSONResponse({"error": {"code": code, "message": str(exc.detail)}}, exc.status_code)

    @app.exception_handler(sqlite3.Error)
    async def db_error(_: Request, exc: sqlite3.Error) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "PIPELINE_COLD", "message": "Data is temporarily unavailable."}}, 503
        )

    v1 = "/api/v1"

    @app.get(f"{v1}/health")
    def health() -> dict:
        """Liveness plus pipeline status. Always 200 while the process is up, so a host
        healthcheck passes before the database is seeded; `status` says whether data exists."""
        extra = {"scheduler_enabled": scheduler is not None, "ticker_updated_at": ticker.updated_at}
        path = db_path()
        if not path.exists():
            return {"status": "cold", "message": "No database yet.", "model_versions":
                    pipeline.model_versions(), **extra}  # fmt: skip
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return {**store.health(conn, pipeline.model_versions()), **extra}
        except sqlite3.Error:
            return {"status": "cold", "message": "Database is not readable yet.",
                    "model_versions": pipeline.model_versions(), **extra}  # fmt: skip
        finally:
            conn.close()

    @app.get(f"{v1}/teams")
    def teams(conn: Conn, response: Response, classification: str | None = None) -> dict:
        response.headers["Cache-Control"] = CACHE_TEAMS
        return envelope(store.all_teams(conn, classification), conn)

    @app.get(f"{v1}/games")
    def games(
        conn: Conn,
        response: Response,
        season: int | None = None,
        week: int | None = None,
        season_type: SeasonType = "regular",
        team: int | None = None,
        conference: str | None = None,
    ) -> dict:
        if season is None or week is None:
            latest = store.latest_week(conn)
            if latest is None:
                raise ApiError(503, "PIPELINE_COLD", "No graded games yet.")
            season, season_type, week = latest  # type: ignore[assignment]
        rows = store.list_games(conn, season, week, season_type, team, conference)
        response.headers["Cache-Control"] = CACHE_WEEK
        return envelope(
            {"season": season, "week": week, "season_type": season_type, "games": rows}, conn
        )

    @app.get(f"{v1}/games/{{game_id}}")
    def game(game_id: int, conn: Conn, response: Response) -> dict:
        data = store.get_game(conn, game_id)
        if data is None:
            raise ApiError(404, "GAME_NOT_FOUND", "No game with that id.")
        settled = data["grading"]["status"] in store.DONE_STATUSES and _older_than_window(
            data["game"]["start_date"]
        )
        response.headers["Cache-Control"] = CACHE_SETTLED if settled else CACHE_SHORT
        return envelope(data, conn)

    @app.get(f"{v1}/scoreboard/latest")
    def scoreboard_latest(
        conn: Conn, response: Response, limit: Annotated[int, Query(ge=1, le=500)] = 50
    ) -> dict:
        latest = store.latest_week(conn)
        if latest is None:
            raise ApiError(503, "PIPELINE_COLD", "No graded games yet.")
        season, season_type, week = latest
        data = store.week_scoreboard(conn, season, week, season_type, limit)
        response.headers["Cache-Control"] = CACHE_SHORT
        return envelope(data, conn)

    @app.get(f"{v1}/scoreboard/week/{{season}}/{{week}}")
    def scoreboard_week(
        season: int,
        week: int,
        conn: Conn,
        response: Response,
        season_type: SeasonType = "regular",
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> dict:
        data = store.week_scoreboard(conn, season, week, season_type, limit)
        if data is None:
            raise ApiError(404, "WEEK_NOT_FOUND", "No games in that week.")
        response.headers["Cache-Control"] = CACHE_WEEK if data["is_complete"] else CACHE_SHORT
        return envelope(data, conn)

    @app.get(f"{v1}/punt-index")
    def punt_index(
        conn: Conn,
        response: Response,
        subject: Literal["coach", "team"] = "coach",
        metric: Literal["wp_lost", "go_rate"] = "wp_lost",
        season_from: int | None = None,
        season_to: int | None = None,
        conference: str | None = None,
        min_games: Annotated[int, Query(ge=0, le=200)] = 6,
        returning: bool = False,
    ) -> dict:
        latest = aggregates.latest_season(conn, min_games) or aggregates.latest_season(conn)
        if latest is None:
            raise ApiError(503, "PIPELINE_COLD", "No graded games yet.")
        season_to = season_to or latest
        season_from = season_from or season_to
        if season_from > season_to:
            raise ApiError(400, "BAD_PARAMS", "season_from must not be after season_to.")
        data = aggregates.punt_index(
            conn, subject, metric, season_from, season_to, conference, min_games, returning
        )
        response.headers["Cache-Control"] = CACHE_WEEK
        return envelope(data, conn)

    @app.get(f"{v1}/punt-index/{{subject}}/{{key}}")
    def punt_index_detail(
        subject: Literal["coach", "team"], key: int, conn: Conn, response: Response
    ) -> dict:
        data = aggregates.punt_index_detail(conn, subject, key)
        if data is None:
            raise ApiError(404, "NOT_FOUND", f"No graded fourth downs for that {subject}.")
        response.headers["Cache-Control"] = CACHE_WEEK
        return envelope(data, conn)

    @app.get(f"{v1}/week-in-review/latest")
    def week_in_review_latest(conn: Conn, response: Response) -> dict:
        latest = aggregates.latest_complete_week(conn)
        if latest is None:
            raise ApiError(503, "PIPELINE_COLD", "No complete week yet.")
        season, season_type, week = latest
        response.headers["Cache-Control"] = CACHE_SHORT
        return envelope(aggregates.week_in_review(conn, season, week, season_type), conn)

    @app.get(f"{v1}/week-in-review/{{season}}/{{week}}")
    def week_in_review(
        season: int,
        week: int,
        conn: Conn,
        response: Response,
        season_type: SeasonType = "regular",
    ) -> dict:
        data = aggregates.week_in_review(conn, season, week, season_type)
        if data is None:
            raise ApiError(404, "WEEK_NOT_FOUND", "No games in that week.")
        response.headers["Cache-Control"] = CACHE_WEEK if data["is_complete"] else CACHE_SHORT
        return envelope(data, conn)

    @app.get(f"{v1}/ticker")
    def ticker_scores(response: Response) -> dict:
        """ESPN scores for the ticker, refreshed by the scheduler. Never fetched per request."""
        response.headers["Cache-Control"] = "public, max-age=20, s-maxage=20"
        return {
            "data": {"games": ticker.games, "games_live": ticker.games_live},
            "meta": {
                "generated_at": ticker.updated_at
                or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "stale": ticker.is_stale(),
                "source": "espn",
            },
        }

    return app


def _older_than_window(start_date: str | None) -> bool:
    if not start_date:
        return False
    start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    return (datetime.now(UTC) - start).days > store.REPROCESS_WINDOW_DAYS


app = create_app()
