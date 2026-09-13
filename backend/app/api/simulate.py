"""Decision simulator (sitemap §5, roadmap Phase 4): evaluate any fourth down on request.

A precomputed table isn't practical: the models take about 25 inputs, and a table would have to
fix most of them. Instead the API runs the same option evaluator as grading (about 70 ms warm),
memoized per model version, and responses are CDN-cacheable.

Inputs the page doesn't expose get documented defaults (defaults(), also returned in every
response):
- Team strength comes from one number, the offense's point spread (negative = favored). It maps
  to Elo through the spread imputer fit on 2011-2025 games, inverted, around the FBS base rating.
- Weather and elevation are the training medians for outdoor games; not indoors; season is the
  latest model season.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from functools import lru_cache

import pandas as pd

from app import decisions as pipeline
from app.api import store
from modeling import inference, options
from modeling.build.elo import INITIAL_RATING
from modeling.config import ARTIFACTS_DIR
from modeling.features import add_state_features

HOME = {"home": 1, "away": -1, "neutral": 0}
SIMILAR_YARDS = 5
EXAMPLES = 5


@dataclass(frozen=True)
class SimInput:
    distance: int
    yards_to_goal: int
    offense_score: int
    defense_score: int
    period: int
    clock_seconds: int
    offense_timeouts: int = 3
    defense_timeouts: int = 3
    spread: float = 0.0
    home: str = "neutral"


@lru_cache(maxsize=1)
def _context() -> dict:
    imputer = json.loads((ARTIFACTS_DIR / "data_build" / "spread_imputer.json").read_text())
    weather = options.assumptions()["weather_defaults"]
    return {"imputer": imputer, "weather": weather}


def _latest_model_season() -> int:
    """The newest season the field goal model's trend covers (it clamps beyond that)."""
    return int(inference._fg_coefficients()["outcome"]["season_clamp"][1])


def defaults() -> dict:
    ctx = _context()
    return {
        "fbs_base_elo": INITIAL_RATING["fbs"],
        "temperature": ctx["weather"]["temperature"],
        "wind_speed": ctx["weather"]["wind_speed"],
        "precipitation": ctx["weather"]["precipitation"],
        "elevation_m": round(ctx["weather"]["elevation_m"], 1),
        "indoors": False,
        "season": _latest_model_season(),
        "spread_to_elo": "inverse of the spread imputer (docs/models.md D9)",
    }


def elo_from_spread(spread: float, home: int) -> tuple[float, float]:
    """Offense and defense Elo whose imputed spread equals `spread` (offense perspective)."""
    imp = _context()["imputer"]
    base = INITIAL_RATING["fbs"]
    # The imputer is from the home team's perspective; neutral sites have no home term.
    home_spread = spread if home >= 0 else -spread
    home_term = imp["home_field"] * (1 if home != 0 else 0)
    home_minus_away = (home_spread - imp["intercept"] - home_term) / imp["elo_diff"]
    offense_minus_defense = home_minus_away if home >= 0 else -home_minus_away
    return base + offense_minus_defense / 2, base - offense_minus_defense / 2


def _state(inp: SimInput) -> pd.DataFrame:
    home = HOME[inp.home]
    off_elo, def_elo = elo_from_spread(inp.spread, home)
    d = defaults()
    return pd.DataFrame(
        [
            {
                "period": inp.period,
                "clock_seconds": float(inp.clock_seconds),
                "offense_score": inp.offense_score,
                "defense_score": inp.defense_score,
                "offense_timeouts": inp.offense_timeouts,
                "defense_timeouts": inp.defense_timeouts,
                "yards_to_goal": inp.yards_to_goal,
                "down": 4,
                "distance": inp.distance,
                "home_indicator": home,
                "offense_spread": inp.spread,
                "offense_elo": off_elo,
                "defense_elo": def_elo,
                "season": d["season"],
                "temperature": d["temperature"],
                "wind_speed": d["wind_speed"],
                "precipitation": d["precipitation"],
                "elevation_m": d["elevation_m"],
                "indoors": 0,
            }
        ]
    )


@lru_cache(maxsize=4096)
def _evaluate_cached(inp: SimInput, version_key: str) -> dict:
    res = pipeline.evaluate(add_state_features(_state(inp))).iloc[0]

    def num(key: str, digits: int = 4) -> float | None:
        value = res.get(key)
        return None if value is None or pd.isna(value) else round(float(value), digits)

    return {
        "recommendation": res["recommendation"],
        "confidence": res["confidence"],
        "margin": num("margin"),
        "wp_go": num("wp_go"),
        "wp_punt": num("wp_punt"),
        "wp_field_goal": num("wp_field_goal"),
        "p_convert": num("p_convert"),
        "p_fg_make": num("p_fg_make"),
        "punt_opponent_yards_to_goal": num("punt_receiving_ytg", 1),
    }


def evaluate(inp: SimInput) -> dict:
    versions = pipeline.model_versions()
    result = dict(_evaluate_cached(inp, json.dumps(versions, sort_keys=True)))
    off_elo, def_elo = elo_from_spread(inp.spread, HOME[inp.home])
    result["inputs"] = {
        **asdict(inp),
        "offense_elo": round(off_elo, 1),
        "defense_elo": round(def_elo, 1),
    }
    result["defaults"] = defaults()
    result["model_versions"] = versions
    return result


def score_bucket(diff: int) -> tuple[int, int]:
    """Score-difference band used to find similar situations (inclusive)."""
    for lo, hi in ((-99, -9), (-8, -4), (-3, -1), (0, 0), (1, 3), (4, 8), (9, 99)):
        if lo <= diff <= hi:
            return lo, hi
    return diff, diff


def distance_band(distance: int) -> tuple[int, int]:
    if distance <= 3:
        return distance, distance
    if distance >= 10:
        return 10, 99
    return distance - 1, distance + 1


def similar(conn: sqlite3.Connection, inp: SimInput) -> dict:
    """Graded FBS fourth downs like this one, 2013 on. Descriptive only, not model input."""
    d_lo, d_hi = distance_band(inp.distance)
    s_lo, s_hi = score_bucket(inp.offense_score - inp.defense_score)
    params = (
        d_lo, d_hi,
        max(1, inp.yards_to_goal - SIMILAR_YARDS), min(99, inp.yards_to_goal + SIMILAR_YARDS),
        s_lo, s_hi, inp.period,
    )  # fmt: skip

    def where(prefix: str = "") -> str:
        return f"""{prefix}offense_classification = 'fbs' AND {prefix}distance BETWEEN ? AND ?
                   AND {prefix}yards_to_goal BETWEEN ? AND ?
                   AND ({prefix}offense_score - {prefix}defense_score) BETWEEN ? AND ?
                   AND {prefix}period = ?"""

    agg = conn.execute(
        f"""SELECT COUNT(*) AS n,
                   AVG(decision = 'go') AS went, AVG(decision = 'punt') AS punted,
                   AVG(decision = 'field_goal') AS kicked, AVG(recommendation = 'go') AS model_go
            FROM plays_fourth_down WHERE {where()}""",
        params,
    ).fetchone()
    # Most recent examples. p.* first, so shared column names (game_id, season...) read from p.
    rows = conn.execute(
        f"""SELECT p.*, g.home_id, g.away_id, g.home_team, g.away_team, g.home_conference,
                   g.away_conference
            FROM plays_fourth_down p JOIN games g ON g.game_id = p.game_id
            WHERE {where("p.")} ORDER BY g.start_date DESC LIMIT ?""",
        (*params, EXAMPLES),
    ).fetchall()
    teams = store.teams_by_id(
        conn, [r["offense_id"] for r in rows] + [r["defense_id"] for r in rows]
    )
    n = agg["n"] or 0

    def rate(value) -> float | None:
        return round(float(value), 4) if n and value is not None else None

    return {
        "similar_situations": n,
        "went_for_it": rate(agg["went"]),
        "punted": rate(agg["punted"]),
        "kicked_field_goal": rate(agg["kicked"]),
        "model_said_go": rate(agg["model_go"]),
        "conversion_rate": None,  # conversion outcomes aren't stored with grades yet
        "criteria": {
            "distance": [d_lo, d_hi],
            "yards_to_goal": [params[2], params[3]],
            "score_diff": [s_lo, s_hi],
            "period": inp.period,
            "scope": "FBS offenses, 2013 on",
        },
        "examples": [store.decision_object(r, r, teams) for r in rows],
    }
