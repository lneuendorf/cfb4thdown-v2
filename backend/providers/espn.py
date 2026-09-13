"""ESPN live provider: fetch (to immutable raw snapshots) and parse to canonical states.

ESPN's site API is undocumented (see docs/v1-audit.md §3). Conventions verified on live data:
- situation.yardLine is measured from the HOME team's goal line; play start/end carry an
  offense-relative yardsToEndzone.
- situation.possession is frequently null; the offense is recovered from the summary's
  current drive or the last play's end team.
- play clock.displayValue is the clock after the play; a leading "(MM:SS)" in the text is the
  snap time. play awayScore/homeScore are post-play.
- Team ids and game (event) ids are identical to CollegeFootballData's.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from providers import rawstore

SOURCE = "espn"
BASE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
FBS_GROUP = 80
SNAP_TEXT = re.compile(r"^\((\d{1,2}):(\d{2})\)")
DISPLAY_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")


class ESPNError(RuntimeError):
    pass


def _get(url: str, params: dict[str, Any], retries: int = 3) -> bytes:
    for attempt in range(retries + 1):
        try:
            resp = httpx.get(url, params=params, timeout=30)
        except httpx.TransportError as exc:
            if attempt == retries:
                raise ESPNError(f"transport error {url}: {exc}") from exc
        else:
            if resp.status_code == 200:
                return resp.content
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise ESPNError(f"{resp.status_code} for {url} {params}")
        time.sleep(2**attempt)
    raise ESPNError(f"gave up on {url}")


def fetch_scoreboard(dates: str | None = None) -> tuple[dict, str]:
    params: dict[str, Any] = {"groups": FBS_GROUP, "limit": 300}
    if dates:
        params["dates"] = dates
    body = _get(f"{BASE}/scoreboard", params)
    path = rawstore.write_snapshot(SOURCE, "scoreboard", (dates or "current",), body)
    return rawstore.read_snapshot(path), str(path)


def fetch_scoreboard_unstored(dates: str | None = None, retries: int = 1) -> dict:
    """Scoreboard for scheduling decisions and the score ticker only, never for grading.

    Not written to the raw store: game_check runs hourly and the ticker every 30-60 s, and
    nothing downstream needs to replay those responses.
    """
    params: dict[str, Any] = {"groups": FBS_GROUP, "limit": 300}
    if dates:
        params["dates"] = dates
    return json.loads(_get(f"{BASE}/scoreboard", params, retries=retries))


def fetch_summary(event_id: str) -> tuple[dict, str]:
    body = _get(f"{BASE}/summary", {"event": event_id})
    path = rawstore.write_snapshot(SOURCE, "summary", (str(event_id),), body)
    return rawstore.read_snapshot(path), str(path)


# ---------------------------------------------------------------- parsing


@dataclass
class LiveGame:
    game_id: int
    state: str  # pre | in | post
    period: int
    clock_seconds: float
    home_id: int
    away_id: int
    home_score: int
    away_score: int
    neutral_site: bool
    situation: dict = field(default_factory=dict)
    detail: str = ""


def parse_scoreboard(scoreboard: dict) -> list[LiveGame]:
    games = []
    for event in scoreboard.get("events", []):
        comp = event["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        status = event["status"]
        games.append(
            LiveGame(
                game_id=int(event["id"]),
                state=status["type"]["state"],
                period=int(status.get("period") or 0),
                clock_seconds=float(status.get("clock") or 0.0),
                home_id=int(teams["home"]["team"]["id"]),
                away_id=int(teams["away"]["team"]["id"]),
                home_score=int(teams["home"].get("score") or 0),
                away_score=int(teams["away"].get("score") or 0),
                neutral_site=bool(comp.get("neutralSite")),
                situation=comp.get("situation") or {},
                detail=status["type"].get("shortDetail", ""),
            )
        )
    return games


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summary_plays(summary: dict) -> list[dict]:
    drives = summary.get("drives") or {}
    plays = [p for d in drives.get("previous", []) for p in d.get("plays", [])]
    current = drives.get("current") or {}
    plays += current.get("plays", [])
    seen, ordered = set(), []
    for p in sorted(plays, key=lambda p: int(p.get("sequenceNumber") or 0)):
        if p["id"] not in seen:
            seen.add(p["id"])
            ordered.append(p)
    return ordered


def resolve_offense(game: LiveGame, summary: dict | None) -> tuple[int | None, str]:
    """Team id with the ball and how it was determined."""
    possession = _int_or_none(game.situation.get("possession"))
    if possession in (game.home_id, game.away_id):
        return possession, "situation.possession"
    if summary:
        current = (summary.get("drives") or {}).get("current") or {}
        team = _int_or_none((current.get("team") or {}).get("id"))
        if team in (game.home_id, game.away_id):
            return team, "summary.current_drive"
    last = game.situation.get("lastPlay") or {}
    end_team = _int_or_none(((last.get("end") or {}).get("team") or {}).get("id"))
    if end_team in (game.home_id, game.away_id):
        return end_team, "lastPlay.end.team"
    return None, "unresolved"


def timeouts_used_from_plays(plays: list[dict], game: LiveGame, period: int) -> tuple[int, int]:
    """Timeouts used this half by (home, away), counted from timeout plays."""
    half = 1 if period <= 2 else 2
    used = {game.home_id: 0, game.away_id: 0}
    for p in plays:
        if (p.get("type") or {}).get("text") != "Timeout":
            continue
        p_period = int((p.get("period") or {}).get("number") or 0)
        if (1 if p_period <= 2 else 2) != half:
            continue
        # The calling team is the participant flagged "timeout": true.
        caller = next((tp for tp in p.get("teamParticipants") or [] if tp.get("timeout")), None)
        team = _int_or_none((caller or {}).get("id"))
        if team in used:
            used[team] += 1
    return used[game.home_id], used[game.away_id]


# ---------------------------------------------------------------- canonical states

TOTAL_TIMEOUTS = 3


def _clock_from_display(value: str | None) -> float | None:
    m = DISPLAY_CLOCK.match(value or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _base_state(game: LiveGame, offense_id: int) -> dict:
    offense_is_home = offense_id == game.home_id
    return {
        "game_id": game.game_id,
        "offense_id": offense_id,
        "defense_id": game.away_id if offense_is_home else game.home_id,
        "offense_is_home": offense_is_home,
        "home_indicator": 0 if game.neutral_site else (1 if offense_is_home else -1),
    }


def pending_fourth_down(game: LiveGame, summary: dict | None) -> tuple[dict | None, str]:
    """Canonical pre-snap state for a game currently sitting on fourth down."""
    s = game.situation
    if game.state != "in" or s.get("down") != 4:
        return None, "not_fourth_down"
    if not 1 <= game.period <= 4:
        return None, "overtime"
    offense_id, source = resolve_offense(game, summary)
    if offense_id is None:
        return None, "offense_unresolved"
    yard_line = _int_or_none(s.get("yardLine"))
    distance = _int_or_none(s.get("distance"))
    if yard_line is None or distance is None:
        return None, "missing_field_position"
    state = _base_state(game, offense_id)
    ytg = 100 - yard_line if state["offense_is_home"] else yard_line
    if not 1 <= ytg <= 99:
        return None, "invalid_field_position"
    # Scoreboard timeout counts do not reset at halftime (in tonight's capture they implied 4.7
    # timeouts used per second-half poll vs 0.7 in the play-by-play), so timeouts come from
    # counting timeout plays in the summary; the scoreboard is only a fallback.
    if summary is not None:
        home_used, away_used = timeouts_used_from_plays(summary_plays(summary), game, game.period)
        home_to, away_to = TOTAL_TIMEOUTS - home_used, TOTAL_TIMEOUTS - away_used
        timeouts_source = "summary_timeout_plays"
    else:
        home_to = _int_or_none(s.get("homeTimeouts"))
        away_to = _int_or_none(s.get("awayTimeouts"))
        timeouts_source = "scoreboard_situation"
    state.update(
        {
            "period": game.period,
            "clock_seconds": game.clock_seconds,
            "offense_score": game.home_score if state["offense_is_home"] else game.away_score,
            "defense_score": game.away_score if state["offense_is_home"] else game.home_score,
            "offense_timeouts": home_to if state["offense_is_home"] else away_to,
            "defense_timeouts": away_to if state["offense_is_home"] else home_to,
            "yards_to_goal": ytg,
            "down": 4,
            "distance": max(1, min(distance, ytg)),
            "offense_source": source,
            "timeouts_source": timeouts_source,
        }
    )
    return state, "ok"


def completed_fourth_downs(game: LiveGame, summary: dict) -> list[dict]:
    """Pre-snap states for fourth-down plays already in the play-by-play."""
    plays = summary_plays(summary)
    out = []
    for i, p in enumerate(plays):
        start = p.get("start") or {}
        if start.get("down") != 4 or (p.get("type") or {}).get("text") in ("Timeout", "End Period"):
            continue
        offense_id = _int_or_none((start.get("team") or {}).get("id"))
        ytg = _int_or_none(start.get("yardsToEndzone"))
        distance = _int_or_none(start.get("distance"))
        period = int((p.get("period") or {}).get("number") or 0)
        if offense_id not in (game.home_id, game.away_id) or ytg is None or distance is None:
            continue
        prev = plays[i - 1] if i > 0 else None
        home_pre = int(prev["homeScore"]) if prev else 0
        away_pre = int(prev["awayScore"]) if prev else 0
        snap = SNAP_TEXT.match(p.get("text") or "")
        if snap:
            clock, clock_source = int(snap.group(1)) * 60 + int(snap.group(2)), "text_snap"
        elif prev and int((prev.get("period") or {}).get("number") or 0) == period:
            clock = _clock_from_display((prev.get("clock") or {}).get("displayValue"))
            clock_source = "previous_play_end"
        else:
            clock, clock_source = 900, "period_start"
        if clock is None:
            continue
        home_used, away_used = timeouts_used_from_plays(plays[:i], game, period)
        state = _base_state(game, offense_id)
        home = state["offense_is_home"]
        state.update(
            {
                "espn_play_id": str(p["id"]),
                "period": period,
                "clock_seconds": float(clock),
                "clock_source": clock_source,
                "offense_score": home_pre if home else away_pre,
                "defense_score": away_pre if home else home_pre,
                "offense_timeouts": TOTAL_TIMEOUTS - (home_used if home else away_used),
                "defense_timeouts": TOTAL_TIMEOUTS - (away_used if home else home_used),
                "yards_to_goal": ytg,
                "down": 4,
                "distance": max(1, min(distance, ytg)),
                "play_type": (p.get("type") or {}).get("text", ""),
                "play_text": p.get("text") or "",
                "is_penalty": bool(p.get("isPenalty")),
            }
        )
        out.append(state)
    return out
