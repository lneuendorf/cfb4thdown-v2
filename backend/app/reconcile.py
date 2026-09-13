"""Link live (ESPN) fourth-down grades to batch (CFBD) grades for the same plays.

ESPN and CFBD share game and team ids but not play ids. After jobs.process grades a game from
CFBD play-by-play, each live_decisions row is matched to a plays_fourth_down row in the same
game with the same period, offense, distance and yards to goal, and the nearest pre-snap clock
(within CLOCK_TOLERANCE_SECONDS). Yards to goal may differ by one yard between providers, so
an exact-spot miss retries at ±1.

The batch grade then replaces the live grade everywhere (the API serves plays_fourth_down for
graded games); live_batch_links keeps the mapping so old #play-<espn id> links still resolve,
and records whether the two recommendations agreed.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from app import db

CLOCK_TOLERANCE_SECONDS = 20


def reconcile(conn: sqlite3.Connection, game_ids: list[int]) -> dict:
    if not game_ids:
        return {}
    marks = ",".join("?" for _ in game_ids)
    live = pd.read_sql_query(
        f"SELECT * FROM live_decisions WHERE game_id IN ({marks})", conn, params=game_ids
    )
    if live.empty:
        return {"live_decisions": 0}
    batch = pd.read_sql_query(
        f"""SELECT play_id, game_id, period, clock_seconds, offense_id, distance, yards_to_goal,
                   decision, recommendation
            FROM plays_fourth_down WHERE game_id IN ({marks})""",
        conn,
        params=game_ids,
    )
    links, used = [], set()
    for row in live.sort_values(
        ["game_id", "period", "clock_seconds"], ascending=[True, True, False]
    ).itertuples():
        match = _best_match(row, batch, used)
        if match is not None:
            used.add(match["play_id"])
        links.append(
            {
                "espn_play_id": row.espn_play_id,
                "cfbd_play_id": None if match is None else str(match["play_id"]),
                "game_id": int(row.game_id),
                "clock_diff_seconds": None
                if match is None
                else round(abs(float(match["clock_seconds"]) - float(row.clock_seconds)), 1),
                "live_decision": row.decision,
                "batch_decision": None if match is None else match["decision"],
                "live_recommendation": row.recommendation,
                "batch_recommendation": None if match is None else match["recommendation"],
                "recommendation_agrees": None
                if match is None
                else int(match["recommendation"] == row.recommendation),
                "linked_at": db.now_iso(),
            }
        )
    frame = pd.DataFrame(links)
    conn.execute(f"DELETE FROM live_batch_links WHERE game_id IN ({marks})", game_ids)
    db.upsert_rows(conn, "live_batch_links", frame)
    matched = frame[frame["cfbd_play_id"].notna()]
    return {
        "live_decisions": len(frame),
        "matched": len(matched),
        "unmatched": int(frame["cfbd_play_id"].isna().sum()),
        "recommendations_agree": int(matched["recommendation_agrees"].sum()) if len(matched) else 0,
        "decisions_agree": int((matched["live_decision"] == matched["batch_decision"]).sum()),
        "batch_without_live": len(batch) - len(used),
    }


def _best_match(row, batch: pd.DataFrame, used: set) -> dict | None:
    same = batch[
        (batch["game_id"] == row.game_id)
        & (batch["period"] == row.period)
        & (batch["offense_id"] == row.offense_id)
        & (batch["distance"] == row.distance)
        & ~batch["play_id"].isin(used)
    ]
    for tolerance in (0, 1):
        spot = same[(same["yards_to_goal"] - row.yards_to_goal).abs() <= tolerance]
        if spot.empty:
            continue
        diff = (spot["clock_seconds"] - row.clock_seconds).abs()
        close = spot[diff <= CLOCK_TOLERANCE_SECONDS]
        if not close.empty:
            return close.loc[diff[close.index].idxmin()].to_dict()
    return None
