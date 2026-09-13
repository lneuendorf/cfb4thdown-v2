"""Save captured ESPN live sessions as fixtures and export them as API-shaped JSON for the UI.

    uv run python -m analysis.live_fixtures save --session 2026-09-12
    uv run python -m analysis.live_fixtures export --session 2026-09-12

save    Copies a capture from data/raw/espn (which is gitignored and may be pruned) into
        fixtures/espn/<session>/: every scoreboard that shows a game on fourth down, every Nth
        scoreboard otherwise, every summary, and the pregame snapshot rows for the session's
        games. The raw layout is kept, so providers.rawstore reads it with root=.
export  Replays a saved session through the live parsing and grading code and writes
        `GET /scoreboard/live` payloads (docs/api-contract.md) to
        frontend/src/dev/fixtures/live/<session>/: a few named scenes plus a short sequence of
        consecutive polls, so the dev live preview can show pending cards appearing and clearing.

These are real ESPN game states graded by the real models. They are for local development of
the live layout only and never ship as user-facing data.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app import db
from jobs import live_poll
from modeling.config import RAW_DIR
from providers import espn, rawstore

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND / "fixtures" / "espn"
FRONTEND_OUT = BACKEND.parent / "frontend" / "src" / "dev" / "fixtures" / "live"
SEQUENCE_LENGTH = 20


# ---------------------------------------------------------------- save


def _board_has_fourth_down(path: Path) -> bool:
    games = espn.parse_scoreboard(rawstore.read_snapshot(path))
    return any(g.state == "in" and g.situation.get("down") == 4 for g in games)


def save(session: str, every: int, since: str | None, until: str | None) -> None:
    boards = rawstore.list_snapshots("espn", "scoreboard", "current")
    if since:
        boards = [b for b in boards if b.name >= since]
    if until:
        boards = [b for b in boards if b.name <= until]
    if not boards:
        raise SystemExit("no captured scoreboards in data/raw/espn for that window")
    root = FIXTURES / session
    kept = [b for i, b in enumerate(boards) if i % every == 0 or _board_has_fourth_down(b)]
    for b in kept:
        _copy(b, root)
    first, last = rawstore.snapshot_time(boards[0]), rawstore.snapshot_time(boards[-1])
    event_ids: set[int] = set()
    for b in kept:
        event_ids.update(g.game_id for g in espn.parse_scoreboard(rawstore.read_snapshot(b)))
    summaries = 0
    for event_dir in sorted(rawstore.snapshot_dir("espn", "summary").iterdir()):
        if int(event_dir.name) not in event_ids:
            continue
        for p in rawstore.list_snapshots("espn", "summary", event_dir.name):
            # Summaries fetched up to a few minutes after the last board complete its plays.
            if rawstore.snapshot_time(p) >= first:
                _copy(p, root)
                summaries += 1
    with db.connect() as conn:
        pregame = live_poll.latest_pregame(conn, sorted(event_ids))
    (root / "pregame.json").write_text(pregame.to_json(orient="records", indent=1))
    manifest = {
        "session": session,
        "saved_at": datetime.now(UTC).isoformat(),
        "captured_from": first.isoformat(),
        "captured_to": last.isoformat(),
        "scoreboards_captured": len(boards),
        "scoreboards_kept": len(kept),
        "keep_rule": f"every {every}th scoreboard plus every one with a game on fourth down",
        "summaries_kept": summaries,
        "games": len(event_ids),
        "games_with_pregame_snapshot": int(pregame["game_id"].nunique()) if len(pregame) else 0,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest, indent=1))


def _copy(path: Path, root: Path) -> None:
    dest = root / path.relative_to(RAW_DIR)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(path, dest)


# ---------------------------------------------------------------- export


def _clock(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _float(value) -> float | None:
    return None if value is None or pd.isna(value) else round(float(value), 4)


class Teams:
    """Team display fields from ESPN scoreboards, keyed by canonical (CFBD = ESPN) team id."""

    def __init__(self) -> None:
        self._teams: dict[int, dict] = {}

    def add_board(self, board: dict) -> None:
        for event in board.get("events", []):
            for c in event["competitions"][0]["competitors"]:
                t = c["team"]
                self._teams[int(t["id"])] = {
                    "id": str(t["id"]),
                    "name": t.get("shortDisplayName") or t.get("location") or t.get("name"),
                    "abbreviation": t.get("abbreviation"),
                    "conference": None,  # ESPN only gives a numeric conferenceId; CFBD /teams later
                    "logo_url": t.get("logo"),
                    "color": f"#{t['color']}" if t.get("color") else None,
                }

    def get(self, team_id: int) -> dict:
        return self._teams.get(int(team_id), {"id": str(team_id), "name": str(team_id)})


def _summaries_at(root: Path, at: datetime) -> live_poll.SummarySource:
    source = live_poll.SummarySource()
    summary_dir = rawstore.snapshot_dir("espn", "summary", root=root)
    if not summary_dir.exists():
        return source
    for event_dir in summary_dir.iterdir():
        path = rawstore.latest_snapshot(
            "espn", "summary", event_dir.name, at_or_before=at, root=root
        )
        if path is not None:
            source.put(int(event_dir.name), rawstore.read_snapshot(path), str(path))
    return source


def payload(conn, root: Path, board_path: Path, teams: Teams) -> dict:
    at = rawstore.snapshot_time(board_path)
    board = rawstore.read_snapshot(board_path)
    games = espn.parse_scoreboard(board)
    by_id = {g.game_id: g for g in games}
    live = [g for g in games if g.state == "in"]
    summaries = _summaries_at(root, at)
    pending_df, _ = live_poll.pending_rows(live, summaries, conn, at.isoformat(), str(board_path))
    decided, _ = live_poll.decision_rows(games, summaries, conn, at.isoformat())

    decisions = []
    for r in decided.to_dict("records") if len(decided) else []:
        g = by_id[int(r["game_id"])]
        offense_home = int(r["offense_id"]) == g.home_id
        defense_id = g.away_id if offense_home else g.home_id
        decisions.append(
            {
                "id": str(r["espn_play_id"]),
                "game_id": str(r["game_id"]),
                "season": at.year if at.month > 2 else at.year - 1,
                "week": None,
                "offense": teams.get(r["offense_id"]),
                "defense": teams.get(defense_id),
                "period": int(r["period"]),
                "clock": _clock(r["clock_seconds"]),
                "down": 4,
                "distance": int(r["distance"]),
                "yard_line": int(r["yards_to_goal"]),
                "yards_to_goal": int(r["yards_to_goal"]),
                "offense_score": int(r["offense_score"]),
                "defense_score": int(r["defense_score"]),
                "recommendation": r["recommendation"],
                "decision": r["decision"],
                "confidence": r["confidence"],
                "margin": _float(r["margin"]),
                "wp_go": _float(r["wp_go"]),
                "wp_punt": _float(r["wp_punt"]),
                "wp_field_goal": _float(r["wp_field_goal"]),
                "wp_delta": _float(r["wp_delta"]),
                "verdict": r["verdict"],
                "outcome": None,
                "play_text": r["play_text"],
                "is_live": g.state == "in",
            }
        )
    decisions.sort(key=lambda d: abs(d["wp_delta"] or 0), reverse=True)

    pending = None
    if len(pending_df):
        # One card at a time on the page; take the game latest in its game (most leverage).
        rows = pending_df.assign(state_obj=pending_df["state"].map(json.loads)).to_dict("records")
        rows.sort(key=lambda r: (r["state_obj"]["period"], -r["state_obj"]["clock_seconds"]))
        r = rows[-1]
        s, g = r["state_obj"], by_id[int(r["game_id"])]
        offense_home = int(r["offense_id"]) == g.home_id
        pending = {
            "game_id": str(r["game_id"]),
            "offense": teams.get(r["offense_id"]),
            "defense": teams.get(g.away_id if offense_home else g.home_id),
            "offense_is_home": offense_home,
            "home_score": g.home_score,
            "away_score": g.away_score,
            "period": s["period"],
            "clock": _clock(s["clock_seconds"]),
            "down": 4,
            "distance": s["distance"],
            "yard_line": s["yards_to_goal"],
            "yards_to_goal": s["yards_to_goal"],
            "recommendation": r["recommendation"],
            "confidence": r["confidence"],
            "margin": _float(r["margin"]),
            "wp_go": _float(r["wp_go"]),
            "wp_punt": _float(r["wp_punt"]),
            "wp_field_goal": _float(r["wp_field_goal"]),
        }

    last_delta: dict[str, float | None] = {}
    for d in sorted(decisions, key=lambda d: (d["period"], -_secs(d["clock"]))):
        last_delta[d["game_id"]] = d["wp_delta"]
    status = {"in": "live", "post": "final", "pre": "scheduled"}
    ticker = [
        {
            "game_id": str(g.game_id),
            "away": teams.get(g.away_id).get("abbreviation"),
            "away_score": g.away_score,
            "home": teams.get(g.home_id).get("abbreviation"),
            "home_score": g.home_score,
            "status": status.get(g.state, g.state),
            "period": g.period or None,
            "clock": _clock(g.clock_seconds) if g.state == "in" else None,
            "wp_delta_last": last_delta.get(str(g.game_id)),
        }
        for g in sorted(games, key=lambda g: ({"in": 0, "post": 1}.get(g.state, 2), g.game_id))
    ]
    mismatched = [d for d in decisions if d["decision"] != d["recommendation"]]
    return {
        "data": {
            "games_live": len(live),
            "games_total": len(games),
            "fourth_downs_today": len(decisions),
            "wp_lost_today": round(-sum(d["wp_delta"] or 0 for d in mismatched), 4),
            "followed_model_rate": (
                round(1 - len(mismatched) / len(decisions), 4) if decisions else None
            ),
            "pending": pending,
            "decisions": decisions,
            "ticker": ticker,
        },
        "meta": {
            "generated_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stale": False,
            "source": "fixture",
        },
    }


def _secs(clock: str) -> int:
    m, s = clock.split(":")
    return int(m) * 60 + int(s)


def export(session: str) -> None:
    root = FIXTURES / session
    if not (root / "manifest.json").exists():
        raise SystemExit(f"no saved session at {root}; run save first")
    boards = rawstore.list_snapshots("espn", "scoreboard", "current", root=root)
    parsed = [(b, espn.parse_scoreboard(rawstore.read_snapshot(b))) for b in boards]

    def live_count(games):
        return sum(g.state == "in" for g in games)

    def has_pending(games):
        return any(g.state == "in" and g.situation.get("down") == 4 for g in games)

    teams = Teams()
    for b, _ in parsed:
        teams.add_board(rawstore.read_snapshot(b))
    busiest = max(live_count(g) for _, g in parsed)
    scenes: dict[str, tuple[Path, str]] = {}
    with_pending = [(b, g) for b, g in parsed if has_pending(g)]
    if with_pending:
        b, _ = max(with_pending, key=lambda x: (live_count(x[1]), x[0].name))
        scenes["busy-pending"] = (b, "Most games live, with a game sitting on fourth down")
        b, _ = min(with_pending, key=lambda x: (live_count(x[1]), x[0].name))
        scenes["late-pending"] = (b, "Fewest games live, with a game sitting on fourth down")
    without = [(b, g) for b, g in parsed if not has_pending(g) and live_count(g)]
    if without:
        b, _ = max(without, key=lambda x: (live_count(x[1]), x[0].name))
        scenes["busy-no-pending"] = (b, "Most games live, no pending fourth down")
    scenes["last-poll"] = (parsed[-1][0], "Last captured poll of the session")

    out = FRONTEND_OUT / session
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(":memory:")
    conn.executescript(db.SCHEMA)
    pregame = pd.read_json(root / "pregame.json", orient="records", dtype={"snapshot_at": str})
    db.upsert_rows(conn, "pregame_snapshots", pregame)

    index = {"session": session, "busiest_live_games": busiest, "scenes": [], "sequence": []}
    for name, (b, description) in scenes.items():
        (out / f"{name}.json").write_text(json.dumps(payload(conn, root, b, teams)))
        index["scenes"].append(
            {
                "name": name,
                "description": description,
                "polled_at": rawstore.snapshot_time(b).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    # A run of consecutive kept polls centred on the first pending card of the busiest stretch.
    anchor = boards.index(scenes.get("busy-pending", scenes["last-poll"])[0])
    start = max(0, min(anchor - SEQUENCE_LENGTH // 2, len(boards) - SEQUENCE_LENGTH))
    seq_dir = out / "sequence"
    if seq_dir.exists():
        shutil.rmtree(seq_dir)
    seq_dir.mkdir()
    for i, b in enumerate(boards[start : start + SEQUENCE_LENGTH]):
        (seq_dir / f"{i:02d}.json").write_text(json.dumps(payload(conn, root, b, teams)))
        index["sequence"].append(f"{i:02d}")
    (out / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    print(json.dumps(index, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("save")
    s.add_argument("--session", required=True)
    s.add_argument("--every", type=int, default=4, help="keep every Nth non-fourth-down board")
    s.add_argument("--since", help="first snapshot file name to include, e.g. 20260913T0310")
    s.add_argument("--until", help="last snapshot file name to include")
    e = sub.add_parser("export")
    e.add_argument("--session", required=True)
    args = parser.parse_args()
    if args.command == "save":
        save(args.session, args.every, args.since, args.until)
    else:
        export(args.session)


if __name__ == "__main__":
    main()
