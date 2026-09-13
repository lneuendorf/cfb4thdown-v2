"""Read-only queries behind the API, shaped as docs/api-contract.md objects.

Everything here reads SQLite written by the jobs. Nothing calls an upstream API.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from app import grading

GRADING_MESSAGES = {
    "graded": None,
    "failed_quality_gate": (
        "Not graded: the play-by-play doesn't add up to the final score, so the situations "
        "before each snap can't be trusted."
    ),
    "awaiting_plays": "Not graded yet: play-by-play for this game hasn't been published.",
    "not_final": "Not graded yet: the game isn't final.",
    "not_processed": "Not graded yet: this game is waiting to be processed.",
    "no_fourth_downs": "Graded, but no fourth downs were in scope.",
}
DONE_STATUSES = ("graded", "failed_quality_gate")
STALE_AFTER_HOURS = 18
REPROCESS_WINDOW_DAYS = 7


def clock(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


# ------------------------------------------------------------------ teams


def teams_by_id(conn: sqlite3.Connection, ids: Iterable[int]) -> dict[int, dict]:
    ids = sorted({int(i) for i in ids})
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT team_id, school, abbreviation, conference, logo_url, color FROM teams "
        f"WHERE team_id IN ({marks})",
        ids,
    ).fetchall()
    return {r["team_id"]: _team(r) for r in rows}


def _team(r: sqlite3.Row) -> dict:
    return {
        "id": str(r["team_id"]),
        "name": r["school"],
        "abbreviation": r["abbreviation"],
        "conference": r["conference"],
        "logo_url": r["logo_url"],
        "color": f"#{r['color'].lstrip('#')}" if r["color"] else None,
    }


def all_teams(conn: sqlite3.Connection, classification: str | None = None) -> list[dict]:
    sql = "SELECT team_id, school, abbreviation, conference, logo_url, color FROM teams"
    params: tuple = ()
    if classification:
        sql += " WHERE classification = ?"
        params = (classification,)
    return [_team(r) for r in conn.execute(sql + " ORDER BY school", params)]


def _team_or_fallback(
    teams: dict[int, dict], team_id: int, name: str | None, conf: str | None
) -> dict:
    if team_id in teams:
        team = dict(teams[team_id])
        team["conference"] = team["conference"] or conf
        return team
    return {"id": str(team_id), "name": name or str(team_id), "abbreviation": None,
            "conference": conf, "logo_url": None, "color": None}  # fmt: skip


# ------------------------------------------------------------------ games


def _game_status(row: sqlite3.Row, now: datetime) -> str:
    if row["is_final"]:
        return "final"
    start = datetime.fromisoformat(row["start_date"]) if row["start_date"] else None
    if start is not None and start > now:
        return "scheduled"
    return "in_progress"


def grading_status(conn: sqlite3.Connection, game: sqlite3.Row, n_decisions: int) -> str:
    source = conn.execute(
        "SELECT status FROM game_sources WHERE game_id = ?", (game["game_id"],)
    ).fetchone()
    if source is not None:
        status = source["status"]
        if status == "graded" and n_decisions == 0:
            return "no_fourth_downs"
        return status
    if n_decisions:
        return "graded"
    if not game["is_final"]:
        return "not_final"
    gate = conn.execute(
        "SELECT 1 FROM exclusions WHERE game_id = ? AND reason = 'game_failed_quality_gate' "
        "LIMIT 1",
        (game["game_id"],),
    ).fetchone()
    if gate:
        return "failed_quality_gate"
    series = conn.execute("SELECT 1 FROM wp_series WHERE game_id = ? LIMIT 1", (game["game_id"],))
    return "no_fourth_downs" if series.fetchone() else "not_processed"


def _game_summary(
    game: sqlite3.Row, teams: dict[int, dict], agg: dict, status: str, now: datetime
) -> dict:
    return {
        "id": str(game["game_id"]),
        "season": game["season"],
        "week": game["week"],
        "season_type": game["season_type"],
        "start_date": _iso(game["start_date"]),
        "status": _game_status(game, now),
        "neutral_site": bool(game["neutral_site"]),
        "home": _team_or_fallback(
            teams, game["home_id"], game["home_team"], game["home_conference"]
        ),
        "away": _team_or_fallback(
            teams, game["away_id"], game["away_team"], game["away_conference"]
        ),
        "home_score": game["home_points"],
        "away_score": game["away_points"],
        "grading_status": status,
        "fourth_downs": agg.get("fourth_downs", 0),
        "wp_lost": round(agg.get("wp_lost", 0.0), 4),
    }


def _iso(value: str | None) -> str | None:
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _game_aggregates(conn: sqlite3.Connection, game_ids: list[int]) -> dict[int, dict]:
    if not game_ids:
        return {}
    marks = ",".join("?" for _ in game_ids)
    rows = conn.execute(
        f"""SELECT game_id, COUNT(*) AS n,
                   -SUM(CASE WHEN decision != recommendation THEN COALESCE(wp_delta, 0)
                        ELSE 0 END) AS lost
            FROM plays_fourth_down WHERE game_id IN ({marks}) GROUP BY game_id""",
        game_ids,
    )
    return {r["game_id"]: {"fourth_downs": r["n"], "wp_lost": r["lost"] or 0.0} for r in rows}


def list_games(
    conn: sqlite3.Connection,
    season: int,
    week: int,
    season_type: str,
    team: int | None = None,
    conference: str | None = None,
) -> list[dict]:
    sql = "SELECT * FROM games WHERE season = ? AND week = ? AND season_type = ?"
    params: list = [season, week, season_type]
    if team is not None:
        sql += " AND (home_id = ? OR away_id = ?)"
        params += [team, team]
    if conference:
        sql += " AND (home_conference = ? OR away_conference = ?)"
        params += [conference, conference]
    games = conn.execute(sql + " ORDER BY start_date, game_id", params).fetchall()
    ids = [g["game_id"] for g in games]
    teams = teams_by_id(conn, [g["home_id"] for g in games] + [g["away_id"] for g in games])
    aggs = _game_aggregates(conn, ids)
    now = datetime.now(UTC)
    out = []
    for g in games:
        agg = aggs.get(g["game_id"], {})
        out.append(
            _game_summary(g, teams, agg, grading_status(conn, g, agg.get("fourth_downs", 0)), now)
        )
    return out


def get_game(conn: sqlite3.Connection, game_id: int) -> dict | None:
    game = conn.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()
    if game is None:
        return None
    rows = conn.execute(
        "SELECT * FROM plays_fourth_down WHERE game_id = ? "
        "ORDER BY period, clock_seconds DESC, play_id",
        (game_id,),
    ).fetchall()
    teams = teams_by_id(conn, [game["home_id"], game["away_id"]])
    decisions = [decision_object(r, game, teams) for r in rows]
    status = grading_status(conn, game, len(decisions))
    now = datetime.now(UTC)
    agg = {"fourth_downs": len(decisions), "wp_lost": -sum(
        d["wp_delta"] or 0 for d in decisions if d["decision"] != d["recommendation"])}  # fmt: skip
    series = [
        {
            "period": s["period"],
            "clock": clock(s["clock_seconds"]),
            "seconds_remaining": int(round((4 - s["period"]) * 900 + s["clock_seconds"])),
            "home_wp": s["home_wp"],
            "play_id": s["play_id"],
        }
        for s in conn.execute(
            "SELECT period, clock_seconds, home_wp, play_id FROM wp_series "
            "WHERE game_id = ? ORDER BY seq",
            (game_id,),
        )
    ]
    if series and game["is_final"] and game["home_points"] is not None:
        diff = game["home_points"] - game["away_points"]
        final_wp = 1.0 if diff > 0 else 0.0 if diff < 0 else 0.5
        series.append(
            {
                "period": 4,
                "clock": "0:00",
                "seconds_remaining": 0,
                "home_wp": final_wp,
                "play_id": None,
            }
        )
    totals = {}
    for side in ("home", "away"):
        team_id = str(game[f"{side}_id"])
        mine = [d for d in decisions if d["offense"]["id"] == team_id]
        totals[side] = {
            "fourth_downs": len(mine),
            "wp_delta": round(sum(d["wp_delta"] or 0 for d in mine), 4),
        }
    return {
        "game": _game_summary(game, teams, agg, status, now),
        "grading": {"status": status, "message": GRADING_MESSAGES.get(status)},
        "wp_series": series,
        "decisions": decisions,
        "totals": totals,
    }


# ------------------------------------------------------------------ decisions


def decision_object(r: sqlite3.Row, game: sqlite3.Row, teams: dict[int, dict]) -> dict:
    home = r["offense_id"] == game["home_id"]
    off_name, def_name = (
        (game["home_team"], game["away_team"]) if home else (game["away_team"], game["home_team"])
    )
    confs = (game["home_conference"], game["away_conference"])
    off_conf, def_conf = confs if home else confs[::-1]
    versions = json.loads(r["model_versions"])
    return {
        "id": r["play_id"],
        "game_id": str(r["game_id"]),
        "season": r["season"],
        "week": r["week"],
        "season_type": r["season_type"],
        "source": r["source"],
        "offense": _team_or_fallback(teams, r["offense_id"], off_name, off_conf),
        "defense": _team_or_fallback(teams, r["defense_id"], def_name, def_conf),
        "period": r["period"],
        "clock": clock(r["clock_seconds"]),
        "down": 4,
        "distance": r["distance"],
        "yard_line": r["yards_to_goal"],
        "yards_to_goal": r["yards_to_goal"],
        "offense_score": r["offense_score"],
        "defense_score": r["defense_score"],
        "recommendation": r["recommendation"],
        "decision": r["decision"],
        "confidence": r["confidence"],
        "margin": _round(r["margin"]),
        "wp_go": _round(r["wp_go"]),
        "wp_punt": _round(r["wp_punt"]),
        "wp_field_goal": _round(r["wp_field_goal"]),
        "wp_delta": _round(r["wp_delta"]),
        "verdict": r["verdict"],
        "outcome": None,
        "play_type": r["play_type"],
        "play_text": r["play_text"],
        "is_live": False,
        "clock_source": r["clock_source"],
        "timeouts_imputed": bool(r["timeouts_imputed"]),
        "model_version": versions.get("win_probability"),
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


# ------------------------------------------------------------------ scoreboards


def latest_week(conn: sqlite3.Connection) -> tuple[int, str, int] | None:
    row = conn.execute(
        """SELECT g.season, g.season_type, g.week, MAX(g.start_date) AS last
           FROM games g JOIN plays_fourth_down p ON p.game_id = g.game_id
           GROUP BY g.season, g.season_type, g.week ORDER BY last DESC LIMIT 1"""
    ).fetchone()
    return (row["season"], row["season_type"], row["week"]) if row else None


def week_scoreboard(
    conn: sqlite3.Connection, season: int, week: int, season_type: str, limit: int
) -> dict | None:
    games = list_games(conn, season, week, season_type)
    if not games:
        return None
    game_rows = {
        g["game_id"]: g
        for g in conn.execute(
            "SELECT * FROM games WHERE season = ? AND week = ? AND season_type = ?",
            (season, week, season_type),
        )
    }
    rows = conn.execute(
        """SELECT * FROM plays_fourth_down WHERE season = ? AND week = ? AND season_type = ?
           ORDER BY ABS(COALESCE(wp_delta, 0)) DESC, play_id""",
        (season, week, season_type),
    ).fetchall()
    ids = [g["home_id"] for g in game_rows.values()] + [g["away_id"] for g in game_rows.values()]
    teams = teams_by_id(conn, ids)
    mismatched = [r for r in rows if r["decision"] != r["recommendation"]]
    graded_games = len({r["game_id"] for r in rows})
    return {
        "season": season,
        "week": week,
        "season_type": season_type,
        "is_complete": all(g["status"] == "final" for g in games),
        "games_live": 0,
        "games_total": len(games),
        "games_graded": sum(g["grading_status"] in ("graded", "no_fourth_downs") for g in games),
        "fourth_downs_today": len(rows),
        "wp_lost_today": round(-sum(r["wp_delta"] or 0 for r in mismatched), 4),
        "followed_model_rate": round(1 - len(mismatched) / len(rows), 4) if rows else None,
        "wp_lost_per_game": round(-sum(r["wp_delta"] or 0 for r in mismatched) / graded_games, 4)
        if graded_games
        else None,
        "pending": None,
        "decisions": [decision_object(r, game_rows[r["game_id"]], teams) for r in rows[:limit]],
        "decisions_total": len(rows),
        "games": games,
        "ticker": [],
    }


# ------------------------------------------------------------------ freshness and health


def pipeline_stale(conn: sqlite3.Connection, now: datetime | None = None) -> bool:
    """True when a recent final game has gone STALE_AFTER_HOURS without being graded."""
    now = now or datetime.now(UTC)
    row = conn.execute(
        f"""SELECT COUNT(*) AS n FROM games g
            LEFT JOIN game_sources s ON s.game_id = g.game_id
            WHERE g.is_final = 1 AND g.start_date >= ? AND g.start_date <= ?
              AND (s.status IS NULL OR s.status NOT IN ({",".join("?" for _ in DONE_STATUSES)}))""",
        (
            (now - timedelta(days=REPROCESS_WINDOW_DAYS)).isoformat(),
            (now - timedelta(hours=STALE_AFTER_HOURS)).isoformat(),
            *DONE_STATUSES,
        ),
    ).fetchone()
    return bool(row["n"])


def health(conn: sqlite3.Connection, model_versions: dict) -> dict:
    last_runs = {}
    for job in ("game_check", "process", "pregame_snapshot", "teams", "backfill"):
        r = conn.execute(
            "SELECT run_id, status, started_at, finished_at FROM run_log WHERE job = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (job,),
        ).fetchone()
        last_runs[job] = dict(r) if r else None
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    processed = conn.execute(
        "SELECT COUNT(*) AS n FROM game_sources "
        "WHERE fetched_at >= ? AND status IN ('graded', 'failed_quality_gate')",
        (since,),
    ).fetchone()["n"]
    return {
        "status": "ok",
        "model_versions": model_versions,
        "mistake_threshold": grading.MISTAKE_THRESHOLD,
        "last_runs": last_runs,
        "games_processed_24h": processed,
        "stale": pipeline_stale(conn),
    }
