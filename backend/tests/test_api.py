"""API contract tests against a temporary SQLite database of obviously fake rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import main

HOME, AWAY = 90001, 90002
GAME, UNGRADED = 999000001, 999000002


def _decision(play_id: str, **overrides) -> dict:
    row = {
        "play_id": play_id, "game_id": GAME, "season": 2099, "week": 1, "season_type": "regular",
        "source": "cfbd", "offense_id": HOME, "defense_id": AWAY, "offense_classification": "fbs",
        "period": 2, "clock_seconds": 671.0, "clock_source": "text_snap", "offense_score": 11,
        "defense_score": 11, "offense_timeouts": 3, "defense_timeouts": 3, "timeouts_imputed": 0,
        "yards_to_goal": 44, "distance": 1, "pre_snap_wp": 0.555, "decision": "go",
        "recommendation": "go", "confidence": "clear", "margin": 0.111, "p_convert": 0.666,
        "wp_go": 0.555, "p_fg_make": None, "wp_field_goal": None, "punt_receiving_ytg": 88.0,
        "wp_punt": 0.444, "wp_actual": 0.555, "wp_delta": 0.0, "verdict": "correct",
        "play_type": "Rush", "play_text": "Fake rush", "model_versions": json.dumps(
            {"win_probability": "9.9.9"}), "run_id": "test", "graded_at": "2099-01-01T00:00:00Z",
    }  # fmt: skip
    row.update(overrides)
    return row


@pytest.fixture()
def client(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    recent = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    with db.connect(path) as conn:
        game = {
            "season": 2099, "week": 1, "season_type": "regular", "start_date": recent,
            "neutral_site": 0, "home_id": HOME, "home_team": "Fixture State",
            "home_classification": "fbs", "home_conference": "Fake", "home_points": 22,
            "away_id": AWAY, "away_team": "Mock Tech", "away_classification": "fbs",
            "away_conference": "Fake", "away_points": 11, "is_final": 1,
        }  # fmt: skip
        db.upsert_rows(
            conn,
            "games",
            pd.DataFrame([{**game, "game_id": GAME}, {**game, "game_id": UNGRADED}]),
        )
        db.upsert_rows(
            conn,
            "teams",
            pd.DataFrame(
                [
                    {"team_id": HOME, "school": "Fixture State", "abbreviation": "FXS",
                     "conference": "Fake", "classification": "fbs", "color": "111111",
                     "logo_url": None, "fetched_at": "2099-01-01"},
                ]
            ),  # Mock Tech deliberately missing: the API falls back to the game's names.
        )  # fmt: skip
        db.upsert_rows(
            conn,
            "plays_fourth_down",
            pd.DataFrame(
                [
                    _decision("1"),
                    _decision(
                        "2",
                        offense_id=AWAY,
                        defense_id=HOME,
                        decision="punt",
                        wp_delta=-0.111,
                        verdict="mistake",
                        period=3,
                    ),
                ]
            ),  # fmt: skip
        )
        db.upsert_rows(
            conn,
            "wp_series",
            pd.DataFrame(
                [
                    {"game_id": GAME, "seq": i, "play_id": str(i), "period": 1,
                     "clock_seconds": 900.0 - i, "down": 1, "home_wp": 0.5}
                    for i in range(3)
                ]
            ),
        )  # fmt: skip
        db.upsert_rows(
            conn,
            "exclusions",
            pd.DataFrame(
                [{"play_id": "x", "game_id": UNGRADED, "season": 2099,
                  "reason": "game_failed_quality_gate", "run_id": "test"}]
            ),
        )  # fmt: skip
    monkeypatch.setenv("CFB4THDOWN_DB", str(path))
    return TestClient(main.create_app(scheduler_enabled=False))


def test_game_page_shape(client):
    r = client.get("/api/v1/games/999000001")
    assert r.status_code == 200
    body = r.json()
    assert set(body["meta"]) == {"generated_at", "stale", "source"}
    data = body["data"]
    assert data["grading"]["status"] == "graded"
    assert [d["id"] for d in data["decisions"]] == ["1", "2"]  # chronological
    first = data["decisions"][0]
    assert first["wp_field_goal"] is None and first["offense"]["abbreviation"] == "FXS"
    assert data["decisions"][1]["offense"]["name"] == "Mock Tech"  # fallback without teams row
    assert first["model_version"] == "9.9.9" and first["clock"] == "11:11"
    assert data["wp_series"][-1] == {
        "period": 4, "clock": "0:00", "seconds_remaining": 0, "home_wp": 1.0, "play_id": None,
    }  # fmt: skip
    assert data["totals"]["away"] == {"fourth_downs": 1, "wp_delta": -0.111}
    assert data["game"]["wp_lost"] == 0.111


def test_ungraded_game_says_why(client):
    data = client.get("/api/v1/games/999000002").json()["data"]
    assert data["grading"]["status"] == "failed_quality_gate"
    assert "doesn't add up" in data["grading"]["message"]
    assert data["decisions"] == [] and data["wp_series"] == []


def test_week_scoreboard_ranks_by_impact(client):
    data = client.get("/api/v1/scoreboard/week/2099/1").json()["data"]
    assert [d["id"] for d in data["decisions"]] == ["2", "1"]
    assert data["fourth_downs_today"] == 2 and data["followed_model_rate"] == 0.5
    assert data["wp_lost_today"] == 0.111 and data["games_total"] == 2
    latest = client.get("/api/v1/scoreboard/latest?limit=1").json()["data"]
    assert (latest["season"], latest["week"], len(latest["decisions"])) == (2099, 1, 1)
    assert latest["decisions_total"] == 2


def test_errors_use_the_contract_shape(client):
    missing = client.get("/api/v1/games/1")
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"code": "GAME_NOT_FOUND", "message": "No game with that id."}
    }
    bad = client.get("/api/v1/games/not-a-number")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "BAD_PARAMS"
    assert client.get("/api/v1/scoreboard/week/2099/7").status_code == 404


def test_cold_database_is_503(tmp_path, monkeypatch):
    monkeypatch.setenv("CFB4THDOWN_DB", str(tmp_path / "missing.db"))
    r = TestClient(main.create_app(scheduler_enabled=False)).get("/api/v1/games/1")
    assert r.status_code == 503 and r.json()["error"]["code"] == "PIPELINE_COLD"


def test_health_is_200_before_the_database_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("CFB4THDOWN_DB", str(tmp_path / "missing.db"))
    r = TestClient(main.create_app(scheduler_enabled=False)).get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "cold"
