"""Expected win probability of going for it, kicking a field goal, or punting on fourth down.

Inputs are canonical pre-snap states (see modeling.features) for fourth downs, plus the kick
context the field goal model needs: season, wind_speed, precipitation, elevation_m, indoors.

Every post-play assumption is measured (artifacts/decision_assumptions); nothing here is a
hand-picked constant except the model scopes noted below. Outcomes that are distributions
(yards gained on a conversion, punt result) are integrated over equal- or quantile-weighted
points instead of plugging in a mean. States whose clock runs out in the fourth quarter are
resolved deterministically by the score.

    wp_go         = P(convert) * E[WP | converted] + (1 - P(convert)) * WP(turnover on downs)
    wp_field_goal = P(make) * WP(made, kickoff) + (1 - P(make)) * WP(missed)
    wp_punt       = E[WP(opponent ball at punt result)]
"""

from __future__ import annotations

import json
from functools import cache

import numpy as np
import pandas as pd

from modeling import inference
from modeling.config import ARTIFACTS_DIR
from modeling.features import flip_possession

ASSUMPTIONS_VERSION = "2.0.0"
# The field goal model was fit on kicks with yards_to_goal <= 50 (a 67-yard kick).
FIELD_GOAL_MAX_YARDS_TO_GOAL = 50
TD_POINTS = 7  # PAT included; 91% of CFBD touchdown rows move the score by exactly 7
FG_POINTS = 3
MISSED_FG_RECEIVER_MAX_YARDS_TO_GOAL = 80  # NCAA: miss from inside the 20 comes out to the 20
PUNT_QUANTILE_WEIGHTS = {  # weights for residual quantiles 5/10/25/50/75/90/95
    0.05: 0.075,
    0.1: 0.1,
    0.25: 0.2,
    0.5: 0.25,
    0.75: 0.2,
    0.9: 0.1,
    0.95: 0.075,
}
CHUNK = 20_000


@cache
def assumptions() -> dict:
    path = ARTIFACTS_DIR / "decision_assumptions" / ASSUMPTIONS_VERSION / "assumptions.json"
    return json.loads(path.read_text())


def _bucket(value: float, edges: list[tuple[int, int]]) -> str:
    for lo, hi in edges:
        if lo <= value <= hi:
            return f"{lo}-{hi}"
    lo, hi = edges[-1]
    return f"{lo}-{hi}"


def _runoff(name: str, state: pd.DataFrame) -> np.ndarray:
    table = assumptions()["snap_to_next_snap_seconds"][name]
    left_in_half = np.where(state["period"] <= 2, 2 - state["period"], 4 - state["period"]) * 900
    late = (left_in_half + state["clock_seconds"]) <= 120
    return np.where(late, table["median_seconds_final_2_minutes_of_half"], table["median_seconds"])


def _advance_clock(state: pd.DataFrame, seconds: np.ndarray) -> pd.DataFrame:
    """Run the clock. Q1/Q3 roll into the next quarter; Q2 stops at 0; Q4 at 0 is terminal."""
    s = state.copy()
    clock = s["clock_seconds"].to_numpy(dtype=float) - seconds
    period = s["period"].to_numpy().copy()
    roll = (clock < 0) & np.isin(period, [1, 3])
    period = np.where(roll, period + 1, period)
    clock = np.where(roll, 900 + clock, clock)
    s["period"] = period
    s["clock_seconds"] = np.maximum(clock, 0)
    s["_terminal"] = (period == 4) & (clock <= 0)
    return s


def _opponent_ball(state: pd.DataFrame, opp_ytg: np.ndarray, seconds: np.ndarray) -> pd.DataFrame:
    s = flip_possession(state)
    ytg = np.clip(np.round(opp_ytg), 1, 99)
    s["yards_to_goal"] = ytg
    s["down"] = 1
    s["distance"] = np.minimum(10, ytg)
    s = _advance_clock(s, seconds)
    s["_perspective"] = -1  # WP returned is the opponent's; flip back
    return s


def _add_points(state: pd.DataFrame, points: int) -> pd.DataFrame:
    s = state.copy()
    s["offense_score"] = s["offense_score"] + points
    return s


def _branches(s: pd.DataFrame) -> pd.DataFrame:
    """One row per (decision row, option component, outcome point) with a weight."""
    a = assumptions()
    parts: list[pd.DataFrame] = []
    ytg = s["yards_to_goal"].to_numpy(dtype=float)
    dist = s["distance"].to_numpy(dtype=float)
    kickoff_start = a["opponent_start_yards_to_goal_after_offensive_td"]["median"]
    fg_kickoff_start = a["opponent_start_yards_to_goal_after_made_fg"]["median"]

    def tag(frame: pd.DataFrame, component: str, weight: np.ndarray | float) -> pd.DataFrame:
        frame = frame.copy()
        frame["_component"] = component
        frame["_weight"] = weight
        if "_perspective" not in frame:
            frame["_perspective"] = 1
        return frame

    # --- go: converted outcomes
    q = a["conversion_yards_beyond_quantiles"]
    edges_y = [(1, 10), (11, 20), (21, 40), (41, 60), (61, 99)]
    edges_d = [(1, 2), (3, 6), (7, 99)]
    keys = [f"{_bucket(y, edges_y)}|{_bucket(d, edges_d)}" for y, d in zip(ytg, dist, strict=True)]
    beyond_table = q["by_ytg_and_distance"]
    fallback = next(iter(beyond_table.values()))["yards_beyond"]
    beyond = np.array(
        [beyond_table.get(k, {"yards_beyond": fallback})["yards_beyond"] for k in keys]
    )
    n_points = beyond.shape[1]
    for i in range(n_points):
        new_ytg = ytg - dist - beyond[:, i]
        goal_to_go = dist >= ytg
        td = goal_to_go | (new_ytg <= 0)
        first_down = s.copy()
        first_down["yards_to_goal"] = np.clip(np.where(td, 1, new_ytg), 1, 99)
        first_down["down"] = 1
        first_down["distance"] = np.minimum(10, first_down["yards_to_goal"])
        first_down = _advance_clock(first_down, _runoff("conversion_same_offense", s))
        first_down["_perspective"] = 1
        scored = _opponent_ball(
            _add_points(s, TD_POINTS),
            np.full(len(s), kickoff_start),
            _runoff("touchdown_then_kickoff", s),
        )
        chosen = first_down.copy()
        for col in scored.columns:
            chosen[col] = np.where(td, scored[col].to_numpy(), first_down[col].to_numpy())
        parts.append(tag(chosen, "go_converted", 1.0 / n_points))

    # --- go: turnover on downs at the line of scrimmage
    fail = _opponent_ball(s, 100 - ytg, _runoff("turnover_on_downs", s))
    parts.append(tag(fail, "go_failed", 1.0))

    # --- field goal
    made = _opponent_ball(
        _add_points(s, FG_POINTS),
        np.full(len(s), fg_kickoff_start),
        _runoff("field_goal_made_then_kickoff", s),
    )
    parts.append(tag(made, "fg_made", 1.0))
    missed = _opponent_ball(
        s,
        np.minimum(100 - ytg, MISSED_FG_RECEIVER_MAX_YARDS_TO_GOAL),
        _runoff("field_goal_missed", s),
    )
    parts.append(tag(missed, "fg_missed", 1.0))

    # --- punt: integrate over residual quantiles of the punt model
    punt_meta = inference.artifact("punt").metadata["residual_quantiles"]
    mean_result = inference.punt_receiving_yards_to_goal(s)
    bucket_labels = np.select(
        [ytg <= 34, ytg <= 44, ytg <= 59, ytg <= 74], ["<35", "35-44", "45-59", "60-74"], "75+"
    )
    table = punt_meta["by_punt_yards_to_goal"]
    for qi, q_level in enumerate(punt_meta["quantiles"]):
        resid = np.array([table[b][qi] for b in bucket_labels])
        result = mean_result + resid
        punted = _opponent_ball(s, result, _runoff("punt", s))
        parts.append(tag(punted, "punt", PUNT_QUANTILE_WEIGHTS[q_level]))

    return pd.concat(parts, ignore_index=True)


def _branch_wp(branches: pd.DataFrame) -> np.ndarray:
    """WP for the original offense at each branch state."""
    wp_holder = inference.win_probability(branches)
    wp = np.where(branches["_perspective"] == 1, wp_holder, 1 - wp_holder)
    terminal = branches["_terminal"].to_numpy(dtype=bool)
    if terminal.any():
        margin = (branches["offense_score"] - branches["defense_score"]).to_numpy()
        # Score margin is from the ball holder's view; convert to the original offense's view.
        margin = np.where(branches["_perspective"] == 1, margin, -margin)
        # Overtime is not modeled: a tie at the end of regulation is scored as a coin flip.
        wp = np.where(terminal, np.select([margin > 0, margin < 0], [1.0, 0.0], 0.5), wp)
    return wp


def evaluate_options(states: pd.DataFrame) -> pd.DataFrame:
    """Per fourth-down state: component probabilities and expected WP of each option."""
    out = []
    for start in range(0, len(states), CHUNK):
        out.append(_evaluate_chunk(states.iloc[start : start + CHUNK].reset_index(drop=True)))
    result = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    result.index = states.index
    return result


def _evaluate_chunk(s: pd.DataFrame) -> pd.DataFrame:
    s = s.copy()
    s["_row"] = np.arange(len(s))
    branches = _branches(s)
    branches["_wp"] = _branch_wp(branches)
    comp = (
        branches.assign(_wx=branches["_wp"] * branches["_weight"])
        .groupby(["_row", "_component"])["_wx"]
        .sum()
        .unstack("_component")
    )
    ytg = s["yards_to_goal"].to_numpy()
    p_convert = inference.conversion_probability(s)
    p_make = inference.field_goal_make_probability(s)
    res = pd.DataFrame(
        {
            "p_convert": p_convert,
            "wp_convert": comp["go_converted"].to_numpy(),
            "wp_fail": comp["go_failed"].to_numpy(),
            "p_fg_make": p_make,
            "wp_fg_made": comp["fg_made"].to_numpy(),
            "wp_fg_missed": comp["fg_missed"].to_numpy(),
            "punt_receiving_ytg": inference.punt_receiving_yards_to_goal(s),
            "wp_punt": comp["punt"].to_numpy(),
        }
    )
    res["wp_go"] = res["p_convert"] * res["wp_convert"] + (1 - res["p_convert"]) * res["wp_fail"]
    res["wp_field_goal"] = (
        res["p_fg_make"] * res["wp_fg_made"] + (1 - res["p_fg_make"]) * res["wp_fg_missed"]
    )
    # XGBoost scores are float32; averaging can overshoot 1 by ~3e-8.
    wp_cols = [
        "wp_convert",
        "wp_fail",
        "wp_fg_made",
        "wp_fg_missed",
        "wp_punt",
        "wp_go",
        "wp_field_goal",
    ]
    res[wp_cols] = res[wp_cols].clip(0.0, 1.0)
    fg_ok = ytg <= FIELD_GOAL_MAX_YARDS_TO_GOAL
    punt_ok = ytg >= assumptions()["punt_model_min_supported_yards_to_goal"]
    for col in ("p_fg_make", "wp_fg_made", "wp_fg_missed", "wp_field_goal"):
        res.loc[~fg_ok, col] = np.nan
    for col in ("punt_receiving_ytg", "wp_punt"):
        res.loc[~punt_ok, col] = np.nan
    return res
