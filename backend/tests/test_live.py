"""Live grading (Phase 6) with obviously fake games (ids 999000xxx, teams 90001/90002)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
import pytest

from app import db, reconcile
from app.api import live
from app.scheduler import kickoff_soon
from jobs.live_poll import LivePoller
from providers import espn, rawstore

HOME, AWAY = 90001, 90002
NOW = datetime(2099, 9, 12, 20, 0, tzinfo=UTC)


def game(game_id: int, state: str, down: int | None = None) -> espn.LiveGame:
    return espn.LiveGame(
        game_id=game_id,
        state=state,
        period=2,
        clock_seconds=300.0,
        home_id=HOME,
        away_id=AWAY,
        home_score=11,
        away_score=11,
        neutral_site=False,
        situation={"down": down} if down else {},
    )


def test_poller_budget_fetches_only_near_fourth_down_or_stale():
    poller = LivePoller()
    now = 10_000.0
    poller.fetched_at = {1: now - 10, 2: now - 10, 3: now - 400, 5: now - 10}
    games = [
        game(1, "in", down=4),  # on fourth down: every poll
        game(2, "in", down=1),  # fresh and not near: skip
        game(3, "in", down=2),  # stale: refresh
        game(4, "in", down=1),  # never fetched: fetch
        game(5, "post"),  # just ended: final summary once
        game(6, "post"),  # never followed live: skip
    ]
    assert poller.due(games, now) == [1, 3, 4, 5]
    poller.final_fetched.add(5)
    assert 5 not in poller.due(games, now)


def test_espn_retries_on_the_fallback_host(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(url)
        if "site.api.espn.com" in url:
            return httpx.Response(403, request=httpx.Request("GET", url))
        return httpx.Response(200, content=b"{}", request=httpx.Request("GET", url))

    monkeypatch.setattr(espn.httpx, "get", fake_get)
    monkeypatch.setattr(espn.time, "sleep", lambda s: None)
    assert espn._get(f"{espn.BASE}/scoreboard", {}, retries=2) == b"{}"
    assert calls[0].startswith(espn.HOSTS[0]) and calls[1].startswith(espn.HOSTS[1])


def _live_row(espn_id: str, **overrides) -> dict:
    row = {
        "espn_play_id": espn_id,
        "game_id": 999000001,
        "polled_at": NOW.isoformat(),
        "raw_snapshot": "fake",
        "offense_id": HOME,
        "period": 2,
        "clock_seconds": 300.0,
        "clock_source": "text_snap",
        "offense_score": 11,
        "defense_score": 11,
        "yards_to_goal": 44,
        "distance": 1,
        "decision": "go",
        "recommendation": "go",
        "confidence": "clear",
        "margin": 0.111,
        "wp_go": 0.555,
        "wp_field_goal": 0.333,
        "wp_punt": 0.444,
        "wp_delta": 0.0,
        "verdict": "correct",
        "play_text": "Fake live rush",
        "model_versions": json.dumps({"win_probability": "9.9.9"}),
    }
    row.update(overrides)
    return row


def _batch_row(play_id: str, **overrides) -> dict:
    row = {
        "play_id": play_id,
        "game_id": 999000001,
        "season": 2099,
        "week": 1,
        "season_type": "regular",
        "source": "cfbd",
        "offense_id": HOME,
        "defense_id": AWAY,
        "offense_classification": "fbs",
        "period": 2,
        "clock_seconds": 296.0,
        "clock_source": "text_snap",
        "offense_score": 11,
        "defense_score": 11,
        "offense_timeouts": 3,
        "defense_timeouts": 3,
        "timeouts_imputed": 0,
        "yards_to_goal": 45,
        "distance": 1,
        "pre_snap_wp": 0.5,
        "decision": "go",
        "recommendation": "go",
        "confidence": "clear",
        "margin": 0.1,
        "wp_go": 0.55,
        "wp_punt": 0.44,
        "wp_field_goal": 0.33,
        "wp_actual": 0.55,
        "wp_delta": 0.0,
        "verdict": "correct",
        "play_type": "Rush",
        "play_text": "Fake batch rush",
        "model_versions": json.dumps({"win_probability": "9.9.9"}),
        "run_id": "t",
        "graded_at": NOW.isoformat(),
    }
    row.update(overrides)
    return row


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "live.db") as c:
        c.row_factory = __import__("sqlite3").Row
        game_row = {
            "game_id": 999000001,
            "season": 2099,
            "week": 1,
            "season_type": "regular",
            "start_date": (NOW - timedelta(hours=1)).isoformat(),
            "neutral_site": 0,
            "home_id": HOME,
            "home_team": "Fixture State",
            "home_classification": "fbs",
            "home_conference": "Fake",
            "home_points": 11,
            "away_id": AWAY,
            "away_team": "Mock Tech",
            "away_classification": "fbs",
            "away_conference": "Fake",
            "away_points": 11,
            "is_final": 0,
        }
        db.upsert_rows(c, "games", pd.DataFrame([game_row]))
        yield c


def test_reconcile_links_live_to_batch_with_clock_and_spot_tolerance(conn):
    db.upsert_rows(
        conn, "live_decisions", pd.DataFrame([_live_row("e1"), _live_row("e2", period=3)])
    )
    db.upsert_rows(conn, "plays_fourth_down", pd.DataFrame([_batch_row("c1")]))
    counts = reconcile.reconcile(conn, [999000001])
    assert counts["matched"] == 1 and counts["unmatched"] == 1
    assert counts["recommendations_agree"] == 1
    link = conn.execute("SELECT * FROM live_batch_links WHERE espn_play_id = 'e1'").fetchone()
    assert link["cfbd_play_id"] == "c1" and link["clock_diff_seconds"] == 4.0


def test_live_scoreboard_serves_live_grades_then_batch(conn):
    db.upsert_rows(
        conn,
        "live_decisions",
        pd.DataFrame([_live_row("e1", wp_delta=-0.111, decision="punt", verdict="mistake")]),
    )
    state = {
        "period": 4,
        "clock_seconds": 120.0,
        "offense_score": 11,
        "defense_score": 11,
        "yards_to_goal": 33,
        "distance": 2,
    }
    pending = {
        "game_id": 999000001,
        "raw_snapshot": "fake",
        "offense_id": AWAY,
        "offense_source": "scoreboard",
        "state": json.dumps(state),
        "recommendation": "go",
        "confidence": "close",
        "margin": 0.02,
        "wp_go": 0.5,
        "wp_field_goal": 0.48,
        "wp_punt": None,
        "model_versions": "{}",
    }
    db.upsert_rows(conn, "live_pending", pd.DataFrame([{**pending, "polled_at": NOW.isoformat()}]))
    ticker = [
        {
            "game_id": "999000001",
            "away": "MKT",
            "away_score": 11,
            "home": "FXS",
            "home_score": 11,
            "status": "live",
            "period": 4,
            "clock": "2:00",
            "start_date": (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ"),
            "wp_delta_last": None,
        }
    ]

    data = live.scoreboard(conn, ticker, NOW)
    assert data["games_live"] == 1 and data["fourth_downs_today"] == 1
    assert data["decisions"][0]["source"] == "espn" and data["decisions"][0]["is_live"]
    assert data["wp_lost_today"] == 0.111 and data["ticker"][0]["wp_delta_last"] == -0.111
    p = data["pending"]
    assert p["offense"]["id"] == str(AWAY) and not p["offense_is_home"]
    assert p["timeouts_uncertain"] and p["wp_punt"] is None

    # A pending card older than PENDING_MAX_AGE_SECONDS is hidden.
    later = NOW + timedelta(seconds=live.PENDING_MAX_AGE_SECONDS + 1)
    assert live.scoreboard(conn, ticker, later)["pending"] is None

    # Once CFBD grades the game, the batch grade replaces the live one.
    db.upsert_rows(conn, "plays_fourth_down", pd.DataFrame([_batch_row("c1")]))
    db.upsert_rows(
        conn,
        "game_sources",
        pd.DataFrame(
            [
                {
                    "game_id": 999000001,
                    "status": "graded",
                    "fetched_at": NOW.isoformat(),
                    "run_id": "t",
                }
            ]
        ),
    )
    data = live.scoreboard(conn, ticker, NOW)
    assert [d["source"] for d in data["decisions"]] == ["cfbd"]


def test_timeouts_uncertain_only_late_in_halves():
    assert live.timeouts_uncertain(2, 200) and live.timeouts_uncertain(4, 300)
    assert not live.timeouts_uncertain(1, 100) and not live.timeouts_uncertain(3, 600)


def test_kickoff_soon():
    soon = (NOW + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%MZ")
    later = (NOW + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%MZ")
    assert kickoff_soon([{"status": "scheduled", "start_date": soon}], NOW)
    assert not kickoff_soon([{"status": "scheduled", "start_date": later}], NOW)
    assert not kickoff_soon([{"status": "final", "start_date": soon}], NOW)


def test_prune_removes_only_old_snapshots(tmp_path):
    old = rawstore.write_snapshot("espn", "scoreboard", ("current",), b"{}", root=tmp_path)
    stale_name = old.with_name("20000101T000000000000Z.json.gz")
    old.rename(stale_name)
    fresh = rawstore.write_snapshot("espn", "scoreboard", ("current",), b"{}", root=tmp_path)
    assert rawstore.prune("espn", 7, root=tmp_path) == 1
    assert fresh.exists() and not stale_name.exists()
