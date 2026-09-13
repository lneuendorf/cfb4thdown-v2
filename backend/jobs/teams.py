"""Refresh team metadata (names, abbreviations, conference, colors, logos) from CFBD.

    uv run python -m jobs.teams

One CFBD call, written to a timestamped raw snapshot, upserted into `teams` by team id.
Colors are stored for completeness; the frontend doesn't use them (design-spec: red and green
are verdict colors only).
"""

from __future__ import annotations

import logging

import pandas as pd

from app import db
from modeling.cfbd import CFBDClient, fetch_snapshot

LOG = logging.getLogger("teams")


def team_rows(rows: list[dict], fetched_at: str) -> pd.DataFrame:
    out = []
    for t in rows:
        logos = t.get("logos") or []
        out.append(
            {
                "team_id": int(t["id"]),
                "school": t["school"],
                "mascot": t.get("mascot"),
                "abbreviation": t.get("abbreviation"),
                "conference": t.get("conference"),
                "classification": t.get("classification"),
                "color": t.get("color"),
                "alt_color": t.get("alternateColor") or t.get("alt_color"),
                "logo_url": logos[0] if logos else None,
                "logo_dark_url": logos[1] if len(logos) > 1 else None,
                "fetched_at": fetched_at,
            }
        )
    return pd.DataFrame(out).drop_duplicates("team_id")


def run(client: CFBDClient | None = None) -> dict:
    client = client or CFBDClient()
    rows, path = fetch_snapshot(client, "teams", {})
    with db.connect() as conn:
        run_id = db.start_run(conn, "teams", {}, {})
        frame = team_rows(rows, db.now_iso())
        db.upsert_rows(conn, "teams", frame)
        counts = {
            "teams": len(frame),
            "with_logo": int(frame["logo_url"].notna().sum()),
            "fbs": int((frame["classification"] == "fbs").sum()),
            "cfbd_calls": client.calls_made,
            "cfbd_remaining": client.last_remaining,
            "raw_snapshot": str(path),
        }
        db.finish_run(conn, run_id, "ok", counts, [])
    LOG.info("teams: %s", counts)
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run()


if __name__ == "__main__":
    main()
