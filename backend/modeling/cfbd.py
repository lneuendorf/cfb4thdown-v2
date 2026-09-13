"""CollegeFootballData client with a write-once raw cache.

Every response is written to data/raw/cfbd/ before anything reads it. A cached response is
never overwritten; delete the file deliberately to force a refetch. Every upstream call is
appended to data/raw/cfbd/_call_log.jsonl so the monthly quota can be audited.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from modeling.config import RAW_DIR

BASE_URL = "https://api.collegefootballdata.com"
BACKOFF_SECONDS = (1, 2, 4, 8, 16)


class CFBDError(RuntimeError):
    pass


def cache_path(endpoint: str, params: dict[str, Any], root: Path = RAW_DIR / "cfbd") -> Path:
    slug = endpoint.strip("/").replace("/", "_")
    key = "__".join(f"{k}={params[k]}" for k in sorted(params)) or "all"
    return root / slug / f"{key}.json.gz"


def read_cached(endpoint: str, params: dict[str, Any], root: Path = RAW_DIR / "cfbd") -> Any:
    path = cache_path(endpoint, params, root)
    if not path.exists():
        raise FileNotFoundError(f"No cached response for {endpoint} {params} at {path}")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


class CFBDClient:
    def __init__(
        self,
        api_key: str | None = None,
        root: Path = RAW_DIR / "cfbd",
        min_interval_seconds: float = 0.5,
    ) -> None:
        key = api_key or os.environ.get("CFBD_API_KEY")
        if not key:
            raise CFBDError("CFBD_API_KEY is not set")
        self._headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        self.root = root
        self.min_interval_seconds = min_interval_seconds
        self._last_call = 0.0
        self.calls_made = 0
        self.last_remaining: int | None = None

    def get(self, endpoint: str, params: dict[str, Any]) -> Any:
        """Return the cached response if present, otherwise fetch, cache, and return it."""
        path = cache_path(endpoint, params, self.root)
        if path.exists():
            return read_cached(endpoint, params, self.root)
        body = self._fetch(endpoint, params)
        self._write_once(path, body, endpoint, params)
        return json.loads(body)

    def _fetch(self, endpoint: str, params: dict[str, Any]) -> bytes:
        url = f"{BASE_URL}/{endpoint.strip('/')}"
        for attempt, delay in enumerate((0, *BACKOFF_SECONDS)):
            if delay:
                time.sleep(delay)
            wait = self.min_interval_seconds - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                resp = httpx.get(url, params=params, headers=self._headers, timeout=180)
            except httpx.TransportError as exc:
                self._log(endpoint, params, status=None, nbytes=0, note=repr(exc))
                if attempt == len(BACKOFF_SECONDS):
                    raise CFBDError(f"Transport error for {url} {params}: {exc}") from exc
                continue
            self.calls_made += 1
            remaining = resp.headers.get("x-calllimit-remaining")
            self.last_remaining = int(remaining) if remaining is not None else None
            self._log(endpoint, params, status=resp.status_code, nbytes=len(resp.content))
            if resp.status_code == 200:
                return resp.content
            if resp.status_code == 429 or resp.status_code >= 500:
                continue
            raise CFBDError(f"{resp.status_code} for {url} {params}: {resp.text[:300]}")
        raise CFBDError(f"Gave up after retries: {url} {params}")

    def _write_once(self, path: Path, body: bytes, endpoint: str, params: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, path)
        meta = {
            "endpoint": endpoint,
            "params": params,
            "fetched_at": datetime.now(UTC).isoformat(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
        path.with_name(path.name.replace(".json.gz", ".meta.json")).write_text(json.dumps(meta))

    def _log(
        self,
        endpoint: str,
        params: dict[str, Any],
        status: int | None,
        nbytes: int,
        note: str = "",
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "endpoint": endpoint,
            "params": params,
            "status": status,
            "bytes": nbytes,
            "remaining": self.last_remaining,
            "note": note,
        }
        with open(self.root / "_call_log.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")


def fetch_snapshot(client: CFBDClient, endpoint: str, params: dict[str, Any]) -> tuple[Any, Path]:
    """Always fetch and write a new timestamped snapshot (for data that changes: current season).

    Stored under data/raw/cfbd_snapshots/{endpoint}/{params}/{fetched_at}.json.gz; never
    overwrites. Use for lines, weather forecasts, and in-progress seasons.
    """
    from providers import rawstore

    body = client._fetch(endpoint, params)
    key = "__".join(f"{k}={params[k]}" for k in sorted(params)) or "all"
    path = rawstore.write_snapshot(
        "cfbd_snapshots", endpoint.strip("/").replace("/", "_"), (key,), body
    )
    return json.loads(body), path
