"""Pregame opponent-adjusted success rates, computed from our own play-by-play.

Replaces v1's CFBD-proprietary inputs (PPA-based team strength, CFBD advanced season stats) so
the conversion model does not depend on a single provider's derived metrics (audit S8).

For every weekly cutoff (Monday 00:00 UTC) we fit, per play family (rush, pass):
    success_rate(game, offense) ~ mu + off[offense] + def[defense]
by weighted ridge on team-game aggregates from games before the cutoff. Weights are attempts
times an exponential time decay. Games in the week starting at that cutoff get those ratings,
so a rating never includes the game it is attached to.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import lsqr

HALF_LIFE_DAYS = 200.0
WINDOW_DAYS = 600
RIDGE_DAMP = 6.0
FAMILIES = ("rush", "pass")


def success(
    down: pd.Series, distance: pd.Series, yards: pd.Series, offense_td: pd.Series
) -> pd.Series:
    """Standard success: 50% of distance on 1st, 70% on 2nd, 100% on 3rd/4th, or a TD."""
    need = np.select([down == 1, down == 2], [0.5 * distance, 0.7 * distance], default=distance)
    return (yards >= need) | offense_td


def garbage_time(period: pd.Series, score_diff: pd.Series) -> pd.Series:
    margin = score_diff.abs()
    return (
        ((period == 2) & (margin > 38))
        | ((period == 3) & (margin > 28))
        | ((period == 4) & (margin > 22))
    )


def team_game_rates(plays: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Aggregate successes and attempts per (game, offense, family)."""
    p = plays[
        plays["valid_state"]
        & plays["category"].isin(["rush", "pass"])
        & ~garbage_time(plays["period"], plays["offense_score"] - plays["defense_score"])
    ].copy()
    td = p["offense_points_on_play"] >= 6
    p["success"] = success(p["down"], p["distance"], p["yards_gained"], td).astype(float)
    agg = (
        p.groupby(["game_id", "offense_id", "defense_id", "category"], as_index=False)
        .agg(successes=("success", "sum"), attempts=("success", "size"))
        .rename(columns={"category": "family"})
    )
    return agg.merge(games[["game_id", "start_date"]], on="game_id")


def _fit(
    rows: pd.DataFrame, cutoff: pd.Timestamp
) -> tuple[float, dict[int, float], dict[int, float]]:
    teams = np.unique(np.concatenate([rows["offense_id"], rows["defense_id"]]))
    idx = {t: i for i, t in enumerate(teams)}
    n, k = len(rows), len(teams)
    age = (cutoff - rows["start_date"]).dt.total_seconds().to_numpy() / 86400.0
    w = rows["attempts"].to_numpy() * 0.5 ** (age / HALF_LIFE_DAYS)
    y = (rows["successes"] / rows["attempts"]).to_numpy()
    mu = float(np.average(y, weights=w))
    sw = np.sqrt(w)
    r = np.arange(n)
    X = csr_matrix(
        (
            np.concatenate([sw, sw]),
            (
                np.concatenate([r, r]),
                np.concatenate([rows["offense_id"].map(idx), rows["defense_id"].map(idx) + k]),
            ),
        ),
        shape=(n, 2 * k),
    )
    coef = lsqr(X, sw * (y - mu), damp=RIDGE_DAMP)[0]
    return mu, dict(zip(teams, coef[:k], strict=True)), dict(zip(teams, coef[k:], strict=True))


def weekly_ratings(rates: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Per game and side: pregame adjusted rush/pass success for offense and allowed by defense."""
    g = games[["game_id", "start_date", "home_id", "away_id"]].copy()
    g["cutoff"] = g["start_date"].dt.tz_convert("UTC").dt.floor("D") - pd.to_timedelta(
        g["start_date"].dt.dayofweek, unit="D"
    )
    out = []
    for cutoff, week_games in g.groupby("cutoff"):
        window = rates[
            (rates["start_date"] < cutoff)
            & (rates["start_date"] >= cutoff - pd.Timedelta(days=WINDOW_DAYS))
        ]
        record = {"game_id": week_games["game_id"].to_numpy()}
        for fam in FAMILIES:
            rows = window[window["family"] == fam]
            if len(rows) < 200:
                mu, off, dfn = np.nan, {}, {}
            else:
                mu, off, dfn = _fit(rows, cutoff)
            for side in ("home", "away"):
                ids = week_games[f"{side}_id"]
                record[f"{side}_off_{fam}_sr"] = mu + ids.map(off).fillna(0.0).to_numpy()
                record[f"{side}_def_{fam}_sr"] = mu + ids.map(dfn).fillna(0.0).to_numpy()
                record[f"{side}_{fam}_obs"] = ids.isin(off.keys()).to_numpy()
        out.append(pd.DataFrame(record))
    return pd.concat(out, ignore_index=True)
