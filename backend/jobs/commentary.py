"""Set or clear the optional commentary shown on a Week in Review page.

    uv run python -m jobs.commentary --season 2026 --week 3 --file notes.txt
    uv run python -m jobs.commentary --season 2026 --week 3 --clear

Plain text; blank lines separate paragraphs. Commentary is written by a person, never generated.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app import db


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season-type", default="regular", choices=["regular", "postseason"])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--file", type=Path)
    action.add_argument("--clear", action="store_true")
    args = parser.parse_args()
    key = (args.season, args.season_type, args.week)
    with db.connect() as conn:
        if args.clear:
            conn.execute(
                "DELETE FROM week_commentary WHERE season = ? AND season_type = ? AND week = ?", key
            )
        else:
            body = args.file.read_text().strip()
            conn.execute(
                "INSERT INTO week_commentary (season, season_type, week, body, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(season, season_type, week) "
                "DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
                (*key, body, db.now_iso()),
            )


if __name__ == "__main__":
    main()
