"""Immutable, timestamped raw snapshots for upstream data that changes over time.

The write-once cache in modeling/cfbd.py suits settled history (one file per request key).
Live and current-season data changes, so every fetch here is written as a new file named by
its fetch time and nothing is ever overwritten. Readers pick a snapshot explicitly (usually
the latest at or before some time), which keeps processing replayable from disk.

Layout: data/raw/{source}/{kind}/{key...}/{YYYYmmddTHHMMSSffffffZ}.json.gz
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modeling.config import RAW_DIR

STAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"


def snapshot_dir(source: str, kind: str, *key: str, root: Path = RAW_DIR) -> Path:
    return root.joinpath(source, kind, *[str(k) for k in key])


def write_snapshot(
    source: str, kind: str, key: tuple[str, ...], body: bytes, root: Path = RAW_DIR
) -> Path:
    fetched_at = datetime.now(UTC)
    directory = snapshot_dir(source, kind, *key, root=root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{fetched_at.strftime(STAMP_FORMAT)}.json.gz"
    if path.exists():
        raise FileExistsError(path)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wb") as f:
        f.write(body)
    tmp.rename(path)
    return path


def snapshot_time(path: Path) -> datetime:
    return datetime.strptime(path.name.removesuffix(".json.gz"), STAMP_FORMAT).replace(tzinfo=UTC)


def list_snapshots(source: str, kind: str, *key: str, root: Path = RAW_DIR) -> list[Path]:
    directory = snapshot_dir(source, kind, *key, root=root)
    return sorted(directory.glob("*.json.gz")) if directory.exists() else []


def latest_snapshot(
    source: str, kind: str, *key: str, at_or_before: datetime | None = None, root: Path = RAW_DIR
) -> Path | None:
    paths = list_snapshots(source, kind, *key, root=root)
    if at_or_before is not None:
        paths = [p for p in paths if snapshot_time(p) <= at_or_before]
    return paths[-1] if paths else None


def read_snapshot(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)
