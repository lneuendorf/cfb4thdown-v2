"""Validate live pending-state parsing against the fourth-down plays that followed.

    uv run python -m analysis.validate_live

For every captured scoreboard with a game on fourth down, parse the pending state, then find
the next fourth-down play in that game's final captured play-by-play and compare. Writes
modeling/reports/live_validation.json.
"""

from __future__ import annotations

import json
from collections import Counter

import pandas as pd

from modeling.config import REPORTS_DIR
from providers import espn, rawstore


def main() -> None:
    boards = rawstore.list_snapshots("espn", "scoreboard", "current")
    summary_dir = rawstore.snapshot_dir("espn", "summary")
    event_ids = {int(p.name) for p in summary_dir.iterdir()}
    final_plays = {}
    for e in event_ids:
        s = rawstore.read_snapshot(rawstore.latest_snapshot("espn", "summary", str(e)))
        final_plays[e] = s
    rows, skipped = [], Counter()
    seen = set()
    for path in boards:
        at = rawstore.snapshot_time(path)
        for g in espn.parse_scoreboard(rawstore.read_snapshot(path)):
            if g.state != "in" or g.situation.get("down") != 4:
                continue
            summary_path = rawstore.latest_snapshot(
                "espn", "summary", str(g.game_id), at_or_before=at
            )
            summary = rawstore.read_snapshot(summary_path) if summary_path else None
            state, why = espn.pending_fourth_down(g, summary)
            if state is None:
                skipped[why] += 1
                if why == "invalid_field_position":
                    skipped[
                        f"invalid_detail:{g.situation.get('downDistanceText')}|yardLine={g.situation.get('yardLine')}"
                    ] += 1
                continue
            key = (
                g.game_id,
                g.period,
                state["yards_to_goal"],
                state["distance"],
                state["offense_score"],
                state["defense_score"],
            )
            if key in seen:
                continue
            seen.add(key)
            if g.game_id not in final_plays:
                skipped["no_final_summary"] += 1
                continue
            # The snap that followed: same period, same offense, field position within 5 yards.
            candidates = [
                p
                for p in espn.completed_fourth_downs(g, final_plays[g.game_id])
                if p["period"] == g.period
                and p["offense_id"] == state["offense_id"]
                and abs(p["yards_to_goal"] - state["yards_to_goal"]) <= 5
                and p["clock_seconds"] <= state["clock_seconds"] + 1
            ]
            if not candidates:
                skipped["no_matching_play_in_pbp"] += 1
                continue
            match = max(candidates, key=lambda p: p["clock_seconds"])
            rows.append({
                "game_id": g.game_id,
                "offense_source": state["offense_source"],
                "offense_match": match["offense_id"] == state["offense_id"],
                "ytg_match": match["yards_to_goal"] == state["yards_to_goal"],
                "distance_match": match["distance"] == state["distance"],
                "score_match": (match["offense_score"], match["defense_score"])
                == (state["offense_score"], state["defense_score"]),
                "offense_timeouts_match": match["offense_timeouts"] == state["offense_timeouts"],
                "defense_timeouts_match": match["defense_timeouts"] == state["defense_timeouts"],
                "seconds_before_snap": state["clock_seconds"] - match["clock_seconds"],
                "snap_clock_source": match["clock_source"],
                "play_type": match["play_type"],
            })  # fmt: skip
    df = pd.DataFrame(rows)
    report = {
        "pending_states_matched_to_a_play": len(df),
        "skipped": dict(skipped),
        "offense_source": df["offense_source"].value_counts().to_dict(),
        "agreement": {c: round(float(df[c].mean()), 3) for c in df.columns if c.endswith("_match")},
        "seconds_between_pending_clock_and_snap": df["seconds_before_snap"]
        .describe()
        .round(1)
        .to_dict(),
        "snap_clock_source": df["snap_clock_source"].value_counts().to_dict(),
        "mismatches": df[~df[[c for c in df.columns if c.endswith("_match")]].all(axis=1)].to_dict(
            "records"
        ),
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "live_validation.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
