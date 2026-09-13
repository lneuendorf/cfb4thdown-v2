"""Live fourth-down inference from ESPN.

    uv run python -m jobs.live_poll --once                 # one live poll
    uv run python -m jobs.live_poll --loop --interval 20   # poll while games are live
    uv run python -m jobs.live_poll --replay               # reprocess captured raw snapshots

Every ESPN response is written to data/raw/espn/ before it is parsed, so --replay reproduces a
live session from disk. Pregame context (Elo, spread, weather, venue) comes from the
pregame_snapshots table written by jobs.pregame_snapshot; games without a snapshot are skipped
and counted, never guessed.

Outputs:
    live_pending    one row per game currently sitting on fourth down: the recommendation
                    before the snap. Rows disappear when the game moves on.
    live_decisions  fourth downs already in ESPN's play-by-play, graded like batch decisions.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime

import pandas as pd

from app import db
from app import decisions as pipeline
from modeling import inference
from modeling.build.plays import categorize
from modeling.features import add_state_features
from providers import espn, rawstore

LOG = logging.getLogger("live_poll")
GRADE_COLUMNS = (
    "recommendation", "confidence", "margin", "wp_go", "wp_field_goal", "wp_punt", "wp_delta",
    "verdict",
)  # fmt: skip


def latest_pregame(conn: sqlite3.Connection, game_ids: list[int]) -> pd.DataFrame:
    if not game_ids:
        return pd.DataFrame()
    marks = ",".join("?" for _ in game_ids)
    return pd.read_sql_query(
        f"""SELECT p.* FROM pregame_snapshots p
            JOIN (SELECT game_id, MAX(snapshot_at) AS s FROM pregame_snapshots
                  WHERE game_id IN ({marks}) GROUP BY game_id) m
            ON p.game_id = m.game_id AND p.snapshot_at = m.s""",
        conn,
        params=game_ids,
    )


def with_context(states: pd.DataFrame, pregame: pd.DataFrame) -> pd.DataFrame:
    """Attach pregame context from the offense's perspective; drop games with no snapshot."""
    df = states.merge(pregame, on="game_id", how="inner", suffixes=("", "_pregame"))
    home = df["offense_is_home"].astype(bool)
    df["offense_elo"] = df["home_elo"].where(home, df["away_elo"])
    df["defense_elo"] = df["away_elo"].where(home, df["home_elo"])
    df["offense_spread"] = df["home_spread"].where(home, -df["home_spread"])
    return add_state_features(df)


def pending_rows(games, summaries, conn, polled_at, board_path) -> tuple[pd.DataFrame, Counter]:
    reasons: Counter = Counter()
    states = []
    for g in games:
        state, why = espn.pending_fourth_down(g, summaries.get(g.game_id))
        if state is None:
            if why != "not_fourth_down":
                reasons[why] += 1
            continue
        states.append(state)
    if not states:
        return pd.DataFrame(), reasons
    frame = pd.DataFrame(states)
    pregame = latest_pregame(conn, frame["game_id"].tolist())
    ctx = with_context(frame, pregame)
    reasons["no_pregame_snapshot"] += len(frame) - len(ctx)
    if ctx.empty:
        return pd.DataFrame(), reasons
    res = pipeline.evaluate(ctx)
    state_cols = [
        "period", "clock_seconds", "offense_score", "defense_score", "offense_timeouts",
        "defense_timeouts", "yards_to_goal", "down", "distance", "home_indicator",
    ]  # fmt: skip
    rows = pd.DataFrame(
        {
            "game_id": ctx["game_id"],
            "polled_at": polled_at,
            "raw_snapshot": board_path,
            "offense_id": ctx["offense_id"],
            "offense_source": ctx["offense_source"],
            "state": [json.dumps({c: _plain(r[c]) for c in state_cols}) for _, r in ctx.iterrows()],
            "recommendation": res["recommendation"],
            "confidence": res["confidence"],
            "margin": res["margin"],
            "wp_go": res["wp_go"],
            "wp_field_goal": res["wp_field_goal"],
            "wp_punt": res["wp_punt"],
            "model_versions": json.dumps(pipeline.model_versions()),
        }
    )
    return rows, reasons


def decision_rows(games, summaries, conn, polled_at) -> tuple[pd.DataFrame, Counter]:
    reasons: Counter = Counter()
    states = []
    for g in games:
        summary = summaries.get(g.game_id)
        if summary is None:
            continue
        for s in espn.completed_fourth_downs(g, summary):
            s["raw_snapshot"] = summaries.path(g.game_id)
            states.append(s)
    if not states:
        return pd.DataFrame(), reasons
    frame = pd.DataFrame(states)
    frame = frame[frame["period"].between(1, 4)]
    frame["category"] = categorize(frame)
    frame.loc[
        frame["is_penalty"] & frame["play_text"].str.contains("no play", case=False), "category"
    ] = "penalty"
    excl = pipeline.category_exclusion(frame["category"])
    reasons.update(excl[excl != ""].value_counts().to_dict())
    frame = frame[excl == ""]
    pregame = latest_pregame(conn, frame["game_id"].unique().tolist())
    ctx = with_context(frame, pregame)
    reasons["no_pregame_snapshot"] += len(frame) - len(ctx)
    if ctx.empty:
        return pd.DataFrame(), reasons
    ctx["decision"] = pipeline.classify_decision(ctx["category"])
    ctx["pre_snap_wp"] = inference.win_probability(ctx)
    scope = pipeline.model_scope_exclusion(ctx)
    reasons.update(scope[scope != ""].value_counts().to_dict())
    ctx = ctx[scope == ""].reset_index(drop=True)
    if ctx.empty:
        return pd.DataFrame(), reasons
    res = pipeline.grade_decisions(ctx)
    rows = pd.DataFrame(
        {
            "espn_play_id": ctx["espn_play_id"],
            "game_id": ctx["game_id"],
            "polled_at": polled_at,
            "raw_snapshot": ctx["raw_snapshot"],
            "offense_id": ctx["offense_id"],
            "period": ctx["period"],
            "clock_seconds": ctx["clock_seconds"],
            "clock_source": ctx["clock_source"],
            "offense_score": ctx["offense_score"],
            "defense_score": ctx["defense_score"],
            "yards_to_goal": ctx["yards_to_goal"],
            "distance": ctx["distance"],
            "decision": ctx["decision"],
            **{c: res[c] for c in GRADE_COLUMNS},
            "play_text": ctx["play_text"],
            "model_versions": json.dumps(pipeline.model_versions()),
        }
    )
    return rows, reasons


def _plain(value):
    return value.item() if hasattr(value, "item") else value


class SummarySource:
    """Summaries keyed by game id, with the raw snapshot path each came from."""

    def __init__(self) -> None:
        self._data: dict[int, dict] = {}
        self._paths: dict[int, str] = {}

    def put(self, game_id: int, summary: dict, path: str) -> None:
        self._data[game_id], self._paths[game_id] = summary, path

    def get(self, game_id: int) -> dict | None:
        return self._data.get(game_id)

    def path(self, game_id: int) -> str:
        return self._paths.get(game_id, "")


def process(
    conn, board: dict, board_path: str, polled_at: str, summaries: SummarySource
) -> Counter:
    parsed = espn.parse_scoreboard(board)
    games = [g for g in parsed if g.state == "in"]
    # Games that finished recently still need their last fourth downs graded from the final
    # summary, until batch grading takes over.
    finished = [g for g in parsed if g.state == "post" and summaries.get(g.game_id) is not None]
    counts: Counter = Counter(live_games=len(games))
    pending, reasons = pending_rows(games, summaries, conn, polled_at, board_path)
    counts.update({f"pending_skipped_{k}": v for k, v in reasons.items()})
    live_ids = [g.game_id for g in games]
    pending_ids = pending["game_id"].tolist() if len(pending) else []
    # A game that is no longer on fourth down loses its pending card. (NOT IN (NULL) matches
    # nothing in SQL, so the empty case clears the table explicitly.)
    if pending_ids:
        marks = ",".join("?" for _ in pending_ids)
        conn.execute(f"DELETE FROM live_pending WHERE game_id NOT IN ({marks})", pending_ids)
    else:
        conn.execute("DELETE FROM live_pending")
    db.upsert_rows(conn, "live_pending", pending)
    counts["pending"] = len(pending)
    batch = _batch_graded(conn, [g.game_id for g in games + finished])
    decided, reasons = decision_rows(
        [g for g in games + finished if g.game_id not in batch], summaries, conn, polled_at
    )
    counts.update({f"decision_skipped_{k}": v for k, v in reasons.items()})
    db.upsert_rows(conn, "live_decisions", decided)
    counts["decisions_graded"] = len(decided)
    counts["games_live_ids"] = len(live_ids)
    conn.commit()
    return counts


def _batch_graded(conn, game_ids: list[int]) -> set[int]:
    if not game_ids:
        return set()
    marks = ",".join("?" for _ in game_ids)
    rows = conn.execute(
        f"SELECT game_id FROM game_sources WHERE status = 'graded' AND game_id IN ({marks})",
        game_ids,
    )
    return {r[0] for r in rows}


class LivePoller:
    """Polls with a request budget, keeping summaries between polls.

    Per poll: one scoreboard request, plus a summary only for
    - games on third or fourth down (a pending card may be about to appear or clear);
    - other live games whose summary is older than SUMMARY_REFRESH_SECONDS;
    - games that just went final (once), to grade their last fourth downs.
    v1 fetched every live game's summary every poll (about 48 requests a minute with 15 live
    games at 20 s); this is roughly 15-25.
    """

    SUMMARY_REFRESH_SECONDS = 300

    def __init__(self) -> None:
        self.summaries = SummarySource()
        self.fetched_at: dict[int, float] = {}
        self.final_fetched: set[int] = set()
        self.last_board: dict | None = None

    def due(self, games: list, now: float) -> list[int]:
        out = []
        for g in games:
            if g.state == "in":
                near = g.situation.get("down") in (3, 4)
                stale = now - self.fetched_at.get(g.game_id, float("-inf")) >= (
                    self.SUMMARY_REFRESH_SECONDS
                )
                if near or stale:
                    out.append(g.game_id)
            elif (
                g.state == "post"
                and g.game_id in self.fetched_at
                and g.game_id not in self.final_fetched
            ):
                out.append(g.game_id)
        return out

    def poll(self, conn) -> Counter:
        board, board_path = espn.fetch_scoreboard()
        self.last_board = board
        polled_at = datetime.now(UTC).isoformat()
        games = espn.parse_scoreboard(board)
        now = time.monotonic()
        due = self.due(games, now)
        failed = 0
        for game_id in due:
            try:
                summary, path = espn.fetch_summary(str(game_id))
            except espn.ESPNError as exc:
                failed += 1
                LOG.warning("summary %s failed: %s", game_id, exc)
                continue
            self.summaries.put(game_id, summary, path)
            self.fetched_at[game_id] = now
            if any(g.game_id == game_id and g.state == "post" for g in games):
                self.final_fetched.add(game_id)
        counts = process(conn, board, board_path, polled_at, self.summaries)
        counts["summaries_fetched"] = len(due) - failed
        counts["summaries_failed"] = failed
        return counts


def poll_once(conn) -> Counter:
    return LivePoller().poll(conn)


def replay(conn) -> Counter:
    """Reprocess every captured scoreboard in time order using summaries captured by then."""
    boards = rawstore.list_snapshots("espn", "scoreboard", "current")
    total: Counter = Counter()
    summary_dir = rawstore.snapshot_dir("espn", "summary")
    event_ids = [p.name for p in summary_dir.iterdir()] if summary_dir.exists() else []
    for board_path in boards:
        at = rawstore.snapshot_time(board_path)
        summaries = SummarySource()
        for event_id in event_ids:
            path = rawstore.latest_snapshot("espn", "summary", event_id, at_or_before=at)
            if path is not None:
                summaries.put(int(event_id), rawstore.read_snapshot(path), str(path))
        counts = process(
            conn, rawstore.read_snapshot(board_path), str(board_path), at.isoformat(), summaries
        )
        total.update({k: v for k, v in counts.items() if k != "live_games"})
    # Final pass: latest summary for every game, so every captured fourth down is graded.
    final = SummarySource()
    for event_id in event_ids:
        path = rawstore.latest_snapshot("espn", "summary", event_id)
        final.put(int(event_id), rawstore.read_snapshot(path), str(path))
    captured = {int(e) for e in event_ids}
    last_board = rawstore.read_snapshot(boards[-1])
    games = [g for g in espn.parse_scoreboard(last_board) if g.game_id in captured]
    decided, reasons = decision_rows(games, final, conn, datetime.now(UTC).isoformat())
    db.upsert_rows(conn, "live_decisions", decided)
    total["final_pass_decisions"] = len(decided)
    total.update({f"final_pass_skipped_{k}": v for k, v in reasons.items()})
    total["scoreboards_replayed"] = len(boards)
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    mode.add_argument("--replay", action="store_true")
    parser.add_argument("--interval", type=float, default=20)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    with db.connect() as conn:
        run_id = db.start_run(conn, "live_poll", vars(args), pipeline.model_versions())
        errors: list[str] = []
        total: Counter = Counter()
        try:
            if args.replay:
                total = replay(conn)
            elif args.once:
                total = poll_once(conn)
            else:
                poller = LivePoller()
                while True:
                    counts = poller.poll(conn)
                    total.update(counts)
                    LOG.info("%s", dict(counts))
                    if counts["live_games"] == 0:
                        break
                    time.sleep(args.interval)
        except espn.ESPNError as exc:
            errors.append(repr(exc))
            LOG.error("ESPN error: %s", exc)
        db.finish_run(conn, run_id, "failed" if errors else "ok", dict(total), errors)
    LOG.info("done: %s", dict(total))


if __name__ == "__main__":
    main()
