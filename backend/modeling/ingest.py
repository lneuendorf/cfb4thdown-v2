"""Fetch the raw CFBD data the models need into the write-once raw cache.

    uv run python -m modeling.ingest --dry-run
    uv run python -m modeling.ingest

Scope: games with at least one FBS team (classification=fbs), regular season and postseason.
Games are fetched from ELO_FIRST_SEASON for Elo burn-in; plays, lines and weather only for
TRAIN_SEASONS.
"""

from __future__ import annotations

import argparse
import logging

from modeling.cfbd import CFBDClient, cache_path
from modeling.config import ELO_FIRST_SEASON, SEASON_TYPES, TRAIN_SEASONS

LOG = logging.getLogger("ingest")


def games_requests(first: int, last: int) -> list[tuple[str, dict]]:
    return [
        ("games", {"year": y, "seasonType": st, "classification": "fbs"})
        for y in range(first, last + 1)
        for st in SEASON_TYPES
    ]


def season_requests(seasons: range) -> list[tuple[str, dict]]:
    reqs: list[tuple[str, dict]] = []
    for y in seasons:
        for st in SEASON_TYPES:
            reqs.append(("lines", {"year": y, "seasonType": st}))
            reqs.append(("games/weather", {"year": y, "seasonType": st}))
    reqs.append(("venues", {}))
    return reqs


def plays_requests(client: CFBDClient | None, seasons: range) -> list[tuple[str, dict]]:
    """One request per (season, season type, week) that has an in-scope game."""
    from modeling.cfbd import read_cached

    reqs = []
    for y in seasons:
        for st in SEASON_TYPES:
            params = {"year": y, "seasonType": st, "classification": "fbs"}
            games = client.get("games", params) if client else read_cached("games", params)
            weeks = sorted({g["week"] for g in games})
            for w in weeks:
                reqs.append(
                    ("plays", {"year": y, "week": w, "seasonType": st, "classification": "fbs"})
                )
    return reqs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    last = TRAIN_SEASONS[-1]
    first_stage = games_requests(ELO_FIRST_SEASON, last) + season_requests(TRAIN_SEASONS)
    todo = [(e, p) for e, p in first_stage if not cache_path(e, p).exists()]
    LOG.info("games/lines/weather/venues: %d requests, %d not cached", len(first_stage), len(todo))
    if args.dry_run:
        LOG.info("plays requests are counted after games are cached (one per in-scope week)")
        return

    client = CFBDClient()
    for endpoint, params in first_stage:
        client.get(endpoint, params)
    LOG.info(
        "stage 1 done; upstream calls so far %d, remaining %s",
        client.calls_made,
        client.last_remaining,
    )

    plays = plays_requests(client, TRAIN_SEASONS)
    todo = [(e, p) for e, p in plays if not cache_path(e, p).exists()]
    LOG.info("plays: %d requests, %d not cached", len(plays), len(todo))
    for i, (endpoint, params) in enumerate(plays, 1):
        client.get(endpoint, params)
        if i % 20 == 0:
            LOG.info(
                "plays %d/%d; calls %d, remaining %s",
                i,
                len(plays),
                client.calls_made,
                client.last_remaining,
            )
    LOG.info("done; upstream calls %d, remaining %s", client.calls_made, client.last_remaining)


if __name__ == "__main__":
    main()
