"""Chronological Elo for teams in games with at least one FBS team.

v1 bug this replaces: v1 iterated seasons by week number, so postseason week 1 was processed
alongside regular-season week 1. Bowl games got preseason ratings, and bowl results leaked into
that season's regular-season ratings from week 2 on. Here games are processed strictly in
kickoff order and every rating is keyed by game_id, so season_type cannot collide.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

# Starting rating by classification the first time a team is seen.
INITIAL_RATING = {"fbs": 1500.0, "fcs": 1150.0, "ii": 950.0, "iii": 850.0, "unknown": 950.0}


@dataclass(frozen=True)
class EloParams:
    k: float = 30.0
    home_field: float = 55.0
    season_regression: float = 0.33
    fcs_rating: float = 1150.0
    mov_multiplier: bool = True

    def initial_rating(self, classification: str) -> float:
        if classification == "fcs":
            return self.fcs_rating
        return INITIAL_RATING.get(classification, INITIAL_RATING["unknown"])


def expected_home(home_rating: float, away_rating: float, home_field: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(home_rating + home_field - away_rating) / 400.0))


def run_elo(games: pd.DataFrame, params: EloParams | None = None) -> pd.DataFrame:
    """Return per-game pregame ratings. `games` must contain only final games.

    Ratings regress toward the team's classification baseline at its first game of each season.
    """
    params = params or EloParams()
    games = games.sort_values(["start_date", "game_id"])
    ratings: dict[int, float] = {}
    last_season: dict[int, int] = {}
    out = np.empty((len(games), 3))
    rows = games[
        [
            "season",
            "neutral_site",
            "home_id",
            "home_classification",
            "home_points",
            "away_id",
            "away_classification",
            "away_points",
        ]
    ].itertuples(index=False)
    for i, g in enumerate(rows):
        pre = []
        for team, cls in ((g.home_id, g.home_classification), (g.away_id, g.away_classification)):
            base = params.initial_rating(cls)
            if team not in ratings:
                ratings[team] = base
            elif last_season[team] != g.season:
                ratings[team] = base + (ratings[team] - base) * (1 - params.season_regression)
            last_season[team] = g.season
            pre.append(ratings[team])
        home_pre, away_pre = pre
        hfa = 0.0 if g.neutral_site else params.home_field
        exp = expected_home(home_pre, away_pre, hfa)
        margin = g.home_points - g.away_points
        result = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        mult = 1.0
        if params.mov_multiplier and margin != 0:
            winner_edge = (home_pre + hfa - away_pre) * (1 if margin > 0 else -1)
            mult = math.log(abs(margin) + 1) * 2.2 / (winner_edge * 0.001 + 2.2)
        delta = params.k * mult * (result - exp)
        ratings[g.home_id] = home_pre + delta
        ratings[g.away_id] = away_pre - delta
        out[i] = (home_pre, away_pre, exp)
    return pd.DataFrame(
        {
            "game_id": games["game_id"].to_numpy(),
            "home_pregame_elo": out[:, 0],
            "away_pregame_elo": out[:, 1],
            "elo_home_win_prob": out[:, 2],
        }
    )


def evaluate(games: pd.DataFrame, pregame: pd.DataFrame, seasons: range) -> dict[str, float]:
    df = games.merge(pregame, on="game_id")
    df = df[df.season.isin(seasons) & (df.home_points != df.away_points)]
    y = (df.home_points > df.away_points).astype(float)
    p = df.elo_home_win_prob.clip(1e-6, 1 - 1e-6)
    return {
        "n_games": int(len(df)),
        "log_loss": float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()),
        "brier": float(((p - y) ** 2).mean()),
    }


def tune(games: pd.DataFrame, tune_seasons: range) -> tuple[EloParams, list[dict]]:
    """Small grid search on game-outcome log loss over `tune_seasons` (before training seasons)."""
    results = []
    for k in (20.0, 25.0, 30.0, 35.0, 45.0):
        for hfa in (45.0, 55.0, 65.0):
            for reg in (0.0, 0.1, 0.2, 0.33):
                for fcs in (1000.0, 1150.0, 1300.0):
                    p = EloParams(k=k, home_field=hfa, season_regression=reg, fcs_rating=fcs)
                    metrics = evaluate(games, run_elo(games, p), tune_seasons)
                    results.append({**asdict(p), **metrics})
    best = min(results, key=lambda r: r["log_loss"])
    params = EloParams(
        k=best["k"],
        home_field=best["home_field"],
        season_regression=best["season_regression"],
        fcs_rating=best["fcs_rating"],
    )
    return params, results


def ratings_before(
    final_games: pd.DataFrame, targets: pd.DataFrame, params: EloParams
) -> pd.DataFrame:
    """Pregame ratings for `targets` (game_id, season, start_date, home/away id + classification).

    Replays every final game that kicked off before each target, in kickoff order, and applies
    the season regression for a team's first game of a new season, exactly as run_elo does.
    """
    events = pd.concat(
        [
            # Targets sort before finals at the same kickoff time, so a target never sees its
            # own result when the same game is also in final_games.
            final_games.assign(event_kind=1),
            targets.assign(event_kind=0, home_points=np.nan, away_points=np.nan),
        ],
        ignore_index=True,
    ).sort_values(["start_date", "event_kind", "game_id"])
    ratings: dict[int, float] = {}
    last_season: dict[int, int] = {}
    out = []
    for g in events.itertuples(index=False):
        pre = []
        for team, cls in ((g.home_id, g.home_classification), (g.away_id, g.away_classification)):
            base = params.initial_rating(cls)
            rating = ratings.get(team, base)
            if team in last_season and last_season[team] != g.season:
                rating = base + (rating - base) * (1 - params.season_regression)
            pre.append(rating)
            if g.event_kind == 1:
                ratings[team] = rating
                last_season[team] = g.season
        if g.event_kind == 0:
            out.append(
                {"game_id": g.game_id, "home_pregame_elo": pre[0], "away_pregame_elo": pre[1]}
            )
            continue
        home_pre, away_pre = pre
        hfa = 0.0 if g.neutral_site else params.home_field
        exp = expected_home(home_pre, away_pre, hfa)
        margin = g.home_points - g.away_points
        result = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        mult = 1.0
        if params.mov_multiplier and margin != 0:
            winner_edge = (home_pre + hfa - away_pre) * (1 if margin > 0 else -1)
            mult = math.log(abs(margin) + 1) * 2.2 / (winner_edge * 0.001 + 2.2)
        delta = params.k * mult * (result - exp)
        ratings[g.home_id] = home_pre + delta
        ratings[g.away_id] = away_pre - delta
    return pd.DataFrame(out, columns=["game_id", "home_pregame_elo", "away_pregame_elo"])
