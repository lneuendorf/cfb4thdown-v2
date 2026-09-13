"""Live views: GET /scoreboard/live, live grades on game pages, ticker WP deltas (Phase 6).

Live grades (live_decisions, source "espn") are provisional. Once jobs.process grades a game
from CFBD, the batch grade (plays_fourth_down) is served instead and live_batch_links maps
the old ESPN play ids to CFBD ones.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from app.api import store
from modeling.features import PERIOD_SECONDS

# A pending card older than this is hidden rather than shown stale (the snap has likely happened).
PENDING_MAX_AGE_SECONDS = 90
# Timeouts in live play-by-play are least reliable late in a half (docs/grades.md).
TIMEOUTS_UNCERTAIN_SECONDS = 300
# "Today" on the live scoreboard: live games plus games that kicked off within this window.
TODAY_HOURS = 18


def timeouts_uncertain(period: int, clock_seconds: float) -> bool:
    left_in_half = (2 - period if period <= 2 else 4 - period) * PERIOD_SECONDS + clock_seconds
    return left_in_half <= TIMEOUTS_UNCERTAIN_SECONDS


def batch_graded(conn: sqlite3.Connection, game_ids: list[int]) -> set[int]:
    if not game_ids:
        return set()
    marks = ",".join("?" for _ in game_ids)
    return {
        r["game_id"]
        for r in conn.execute(
            f"SELECT game_id FROM game_sources WHERE status = 'graded' AND game_id IN ({marks})",
            game_ids,
        )
    }


def live_decision_object(r: sqlite3.Row, game: sqlite3.Row, teams: dict, is_live: bool) -> dict:
    home = r["offense_id"] == game["home_id"]
    defense_id = game["away_id"] if home else game["home_id"]
    names = (game["home_team"], game["away_team"])
    confs = (game["home_conference"], game["away_conference"])
    versions = json.loads(r["model_versions"])
    return {
        "id": r["espn_play_id"],
        "game_id": str(r["game_id"]),
        "season": game["season"],
        "week": game["week"],
        "season_type": game["season_type"],
        "source": "espn",
        "offense": store._team_or_fallback(
            teams, r["offense_id"], names[0 if home else 1], confs[0 if home else 1]
        ),
        "defense": store._team_or_fallback(
            teams, defense_id, names[1 if home else 0], confs[1 if home else 0]
        ),
        "period": r["period"],
        "clock": store.clock(r["clock_seconds"]),
        "down": 4,
        "distance": r["distance"],
        "yard_line": r["yards_to_goal"],
        "yards_to_goal": r["yards_to_goal"],
        "offense_score": r["offense_score"],
        "defense_score": r["defense_score"],
        "recommendation": r["recommendation"],
        "decision": r["decision"],
        "confidence": r["confidence"],
        "margin": store._round(r["margin"]),
        "wp_go": store._round(r["wp_go"]),
        "wp_punt": store._round(r["wp_punt"]),
        "wp_field_goal": store._round(r["wp_field_goal"]),
        "wp_delta": store._round(r["wp_delta"]),
        "verdict": r["verdict"],
        "outcome": None,
        "play_type": None,
        "play_text": r["play_text"],
        "is_live": is_live,
        "clock_source": r["clock_source"],
        "timeouts_imputed": False,
        "timeouts_uncertain": timeouts_uncertain(r["period"], r["clock_seconds"]),
        "model_version": versions.get("win_probability"),
    }


def live_decisions_for(
    conn: sqlite3.Connection, game_ids: list[int], live_ids: set[int]
) -> list[dict]:
    if not game_ids:
        return []
    marks = ",".join("?" for _ in game_ids)
    games = {
        g["game_id"]: g
        for g in conn.execute(f"SELECT * FROM games WHERE game_id IN ({marks})", game_ids)
    }
    rows = conn.execute(
        f"SELECT * FROM live_decisions WHERE game_id IN ({marks}) "
        "ORDER BY period, clock_seconds DESC, espn_play_id",
        game_ids,
    ).fetchall()
    ids = [g["home_id"] for g in games.values()] + [g["away_id"] for g in games.values()]
    teams = store.teams_by_id(conn, ids)
    return [
        live_decision_object(r, games[r["game_id"]], teams, r["game_id"] in live_ids)
        for r in rows
        if r["game_id"] in games
    ]


def play_aliases(conn: sqlite3.Connection, game_id: int) -> dict[str, str]:
    return {
        r["espn_play_id"]: r["cfbd_play_id"]
        for r in conn.execute(
            "SELECT espn_play_id, cfbd_play_id FROM live_batch_links "
            "WHERE game_id = ? AND cfbd_play_id IS NOT NULL",
            (game_id,),
        )
    }


def pending_objects(conn: sqlite3.Connection, live_ids: set[int], now: datetime) -> list[dict]:
    cutoff = (now - timedelta(seconds=PENDING_MAX_AGE_SECONDS)).isoformat()
    rows = [
        r
        for r in conn.execute("SELECT * FROM live_pending WHERE polled_at >= ?", (cutoff,))
        if r["game_id"] in live_ids
    ]
    if not rows:
        return []
    marks = ",".join("?" for _ in rows)
    games = {
        g["game_id"]: g
        for g in conn.execute(
            f"SELECT * FROM games WHERE game_id IN ({marks})", [r["game_id"] for r in rows]
        )
    }
    teams = store.teams_by_id(
        conn, [g["home_id"] for g in games.values()] + [g["away_id"] for g in games.values()]
    )
    out = []
    for r in rows:
        game = games.get(r["game_id"])
        if game is None:
            continue
        s = json.loads(r["state"])
        home = r["offense_id"] == game["home_id"]
        home_score, away_score = (
            (s["offense_score"], s["defense_score"])
            if home
            else (s["defense_score"], s["offense_score"])
        )
        out.append(
            {
                "game_id": str(r["game_id"]),
                "offense": store._team_or_fallback(teams, r["offense_id"], None, None),
                "defense": store._team_or_fallback(
                    teams, game["away_id"] if home else game["home_id"], None, None
                ),
                "offense_is_home": bool(home),
                "home_score": home_score,
                "away_score": away_score,
                "period": s["period"],
                "clock": store.clock(s["clock_seconds"]),
                "down": 4,
                "distance": s["distance"],
                "yard_line": s["yards_to_goal"],
                "yards_to_goal": s["yards_to_goal"],
                "recommendation": r["recommendation"],
                "confidence": r["confidence"],
                "margin": store._round(r["margin"]),
                "wp_go": store._round(r["wp_go"]),
                "wp_punt": store._round(r["wp_punt"]),
                "wp_field_goal": store._round(r["wp_field_goal"]),
                "timeouts_uncertain": timeouts_uncertain(s["period"], s["clock_seconds"]),
                "polled_at": r["polled_at"],
                "_leverage": (s["period"], -s["clock_seconds"]),
            }
        )
    # The latest-in-game situation first (the most leverage).
    out.sort(key=lambda p: p.pop("_leverage"), reverse=True)
    return out


def _today(ticker_games: list[dict], now: datetime) -> list[dict]:
    since = now - timedelta(hours=TODAY_HOURS)
    out = []
    for g in ticker_games:
        start = g.get("start_date")
        started = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
        if g["status"] == "live" or (started is not None and since <= started <= now):
            out.append(g)
    return out


def scoreboard(
    conn: sqlite3.Connection, ticker_games: list[dict], now: datetime | None = None
) -> dict:
    now = now or datetime.now(UTC)
    today = _today(ticker_games, now)
    today_ids = [int(g["game_id"]) for g in today]
    live_ids = {int(g["game_id"]) for g in today if g["status"] == "live"}
    batch = batch_graded(conn, today_ids)
    decisions = live_decisions_for(conn, [i for i in today_ids if i not in batch], live_ids)
    if batch:
        marks = ",".join("?" for _ in batch)
        games = {
            g["game_id"]: g
            for g in conn.execute(f"SELECT * FROM games WHERE game_id IN ({marks})", list(batch))
        }
        teams = store.teams_by_id(
            conn, [g["home_id"] for g in games.values()] + [g["away_id"] for g in games.values()]
        )
        decisions += [
            store.decision_object(r, games[r["game_id"]], teams)
            for r in conn.execute(
                f"SELECT * FROM plays_fourth_down WHERE game_id IN ({marks})", list(batch)
            )
        ]
    decisions.sort(key=lambda d: (-abs(d["wp_delta"] or 0), d["id"]))
    mismatched = [d for d in decisions if d["decision"] != d["recommendation"]]
    pendings = pending_objects(conn, live_ids, now)
    deltas = latest_deltas(decisions)
    return {
        "games_live": len(live_ids),
        "games_total": len(today),
        "fourth_downs_today": len(decisions),
        "wp_lost_today": round(-sum(d["wp_delta"] or 0 for d in mismatched), 4),
        "followed_model_rate": round(1 - len(mismatched) / len(decisions), 4)
        if decisions
        else None,
        "pending": pendings[0] if pendings else None,
        "pending_all": pendings,
        "decisions": decisions,
        "ticker": [{**g, "wp_delta_last": deltas.get(g["game_id"])} for g in ticker_games],
    }


def latest_deltas(decisions: list[dict]) -> dict[str, float | None]:
    """Most recent graded fourth down's wp_delta per game, for the ticker."""
    out: dict[str, tuple] = {}
    for d in decisions:
        key = (d["period"], -_seconds(d["clock"]))
        if d["game_id"] not in out or key > out[d["game_id"]][0]:
            out[d["game_id"]] = (key, d["wp_delta"])
    return {k: v[1] for k, v in out.items()}


def _seconds(clock: str) -> int:
    m, s = clock.split(":")
    return int(m) * 60 + int(s)
