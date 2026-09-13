"""Record live ESPN data to raw snapshots for replay (no inference).

    uv run python -m jobs.live_capture --minutes 120 --interval 30

Polls the FBS scoreboard. When a game shows a pending fourth down, fetches that game's
summary about one and three minutes later, so the play that followed can be matched to the
pending state. Everything lands in data/raw/espn/ and can be replayed by jobs.live_poll.
"""

from __future__ import annotations

import argparse
import logging
import time

from providers import espn

LOG = logging.getLogger("live_capture")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=120)
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    deadline = time.monotonic() + args.minutes * 60
    pending_seen: set[tuple] = set()
    summary_due: list[tuple[float, str]] = []
    while time.monotonic() < deadline:
        try:
            board, _ = espn.fetch_scoreboard()
        except espn.ESPNError as exc:
            LOG.warning("scoreboard failed: %s", exc)
            time.sleep(args.interval)
            continue
        games = espn.parse_scoreboard(board)
        live = [g for g in games if g.state == "in"]
        for g in live:
            s = g.situation
            if s.get("down") == 4:
                key = (
                    g.game_id, g.period, s.get("yardLine"), s.get("distance"),
                    g.home_score, g.away_score,
                )  # fmt: skip
                if key not in pending_seen:
                    pending_seen.add(key)
                    now = time.monotonic()
                    summary_due += [(now + 60, str(g.game_id)), (now + 180, str(g.game_id))]
                    LOG.info(
                        "pending 4th: %s %s %s", g.game_id, g.detail, s.get("downDistanceText")
                    )
        now = time.monotonic()
        due = [e for t, e in summary_due if t <= now]
        summary_due = [(t, e) for t, e in summary_due if t > now]
        for event_id in sorted(set(due)):
            try:
                espn.fetch_summary(event_id)
            except espn.ESPNError as exc:
                LOG.warning("summary %s failed: %s", event_id, exc)
        LOG.info(
            "live %d, pending seen %d, summaries fetched %d",
            len(live),
            len(pending_seen),
            len(set(due)),
        )
        if not live and not any(g.state == "pre" for g in games):
            break
        time.sleep(args.interval)
    # Final summaries for every game seen with a fourth down, for full play-by-play replay.
    for event_id in sorted({str(k[0]) for k in pending_seen}):
        try:
            espn.fetch_summary(event_id)
        except espn.ESPNError as exc:
            LOG.warning("final summary %s failed: %s", event_id, exc)


if __name__ == "__main__":
    main()
