"""Scheduling decisions for game_check and process, with fake games (ids 999000xxx)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from app import db
from app.batch import WP_SERIES_MAX_POINTS, _downsample
from app.scheduler import ticker_entries
from jobs import game_check, process

NOW = datetime(2099, 9, 12, 20, 0, tzinfo=UTC)


def event(game_id: int, state: str, start: datetime) -> dict:
    return {
        "id": str(game_id),
        "date": start.strftime("%Y-%m-%dT%H:%MZ"),
        "status": {"clock": 0, "period": 1, "displayClock": "9:99", "type": {"state": state}},
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "score": "22", "team": {"id": "90001",
                                                              "abbreviation": "FXS"}},
                    {"homeAway": "away", "score": "11", "team": {"id": "90002",
                                                              "abbreviation": "MKT"}},
                ]
            }
        ],
    }  # fmt: skip


def board(*events: dict) -> dict:
    return {"leagues": [{"season": {"year": 2099}}], "events": list(events)}


def test_game_check_flags_new_finals_live_and_pregame(tmp_path):
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert_rows(
            conn,
            "game_sources",
            pd.DataFrame(
                [
                    {"game_id": 999000001, "status": "graded", "fetched_at": NOW.isoformat(),
                     "run_id": "t"},
                    # Awaiting plays, checked 30 minutes ago: not retried yet.
                    {"game_id": 999000002, "status": "awaiting_plays",
                     "fetched_at": (NOW - timedelta(minutes=30)).isoformat(), "run_id": "t"},
                ]
            ),
        )  # fmt: skip
        result = game_check.evaluate(
            board(
                event(999000001, "post", NOW - timedelta(hours=5)),
                event(999000002, "post", NOW - timedelta(hours=5)),
                event(999000003, "post", NOW - timedelta(hours=4)),
                event(999000004, "in", NOW - timedelta(hours=1)),
                event(999000005, "pre", NOW + timedelta(hours=2)),
            ),
            conn,
            NOW,
        )
    assert result.season == 2099
    assert result.new_game_ids == [999000003]
    assert result.has_live_games and result.pregame_due
    assert not result.reprocess_due  # 20:00 UTC is not the reprocessing hour


def test_game_check_skips_pregame_with_fresh_snapshot(tmp_path):
    start = NOW + timedelta(hours=2)
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert_rows(
            conn,
            "pregame_snapshots",
            pd.DataFrame(
                [{"game_id": 999000005, "snapshot_at": (NOW - timedelta(hours=1)).isoformat(),
                  "season": 2099, "home_id": 90001, "away_id": 90002, "home_elo": 1111.0,
                  "away_elo": 1111.0, "home_spread": -1.0, "spread_source": "fake", "run_id": "t"}]
            ),
        )  # fmt: skip
        result = game_check.evaluate(board(event(999000005, "pre", start)), conn, NOW)
    assert not result.pregame_due


def test_process_targets_new_finals_and_window():
    games = pd.DataFrame(
        {
            "game_id": [999000001, 999000002, 999000003, 999000004],
            "is_final": [True, True, True, False],
            "start_date": pd.to_datetime(
                [NOW - timedelta(days=2), NOW - timedelta(days=20), NOW - timedelta(days=1), NOW],
                utc=True,
            ),
        }
    )
    sources = pd.DataFrame(
        {"game_id": [999000001, 999000002], "status": ["graded", "failed_quality_gate"]}
    )
    new_only = process.select_targets(games, sources, NOW, False, None)
    assert new_only["game_id"].tolist() == [999000003]
    window = process.select_targets(games, sources, NOW, True, None)
    assert window["game_id"].tolist() == [999000001, 999000003]


def test_plays_hash_ignores_row_order():
    a = [{"id": "2", "x": 1}, {"id": "1", "x": 2}]
    assert process.plays_hash(a) == process.plays_hash(list(reversed(a)))
    assert process.plays_hash(a) != process.plays_hash([{"id": "2", "x": 9}, {"id": "1", "x": 2}])


def test_wp_series_downsample_keeps_fourth_downs():
    n = 500
    game = pd.DataFrame({"seq": range(n), "down": [4 if i % 97 == 5 else 1 for i in range(n)]})
    kept = _downsample(game)
    assert len(kept) <= WP_SERIES_MAX_POINTS + (game["down"] == 4).sum()
    assert set(game.loc[game["down"] == 4, "seq"]) <= set(kept["seq"])


def test_ticker_orders_live_first():
    entries = ticker_entries(
        board(
            event(999000001, "post", NOW - timedelta(hours=3)),
            event(999000002, "in", NOW - timedelta(hours=1)),
        )
    )
    assert [e["status"] for e in entries] == ["live", "final"]
    assert entries[0]["clock"] == "9:99" and entries[1]["clock"] is None
