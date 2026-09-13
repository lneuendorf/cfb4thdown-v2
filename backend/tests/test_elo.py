import pandas as pd

from modeling.build.elo import EloParams, run_elo
from tests.fixtures import game

T1, T2, T3 = 90001, 90002, 90003


def matchup(game_id, season, when, home, away, home_pts, away_pts, **kw) -> dict:
    return game(
        game_id,
        season,
        start_date=pd.Timestamp(when),
        home_id=home,
        away_id=away,
        home_points=home_pts,
        away_points=away_pts,
        **kw,
    )


def schedule() -> pd.DataFrame:
    rows = [
        # Season 2099: T1 beats T2 in week 1, T1 beats T3 in week 2, then a bowl in January.
        matchup(1, 2099, "2099-09-05T18:00Z", T1, T2, 30, 10, week=1),
        matchup(2, 2099, "2099-09-12T18:00Z", T1, T3, 24, 21, week=2),
        matchup(
            3, 2099, "2100-01-01T18:00Z", T2, T3, 45, 0,
            week=1, season_type="postseason", neutral_site=True,
        ),
        # Next season opener.
        matchup(4, 2100, "2100-09-04T18:00Z", T2, T1, 17, 14, week=1),
    ]  # fmt: skip
    return pd.DataFrame(rows)


def test_postseason_week_one_uses_end_of_season_rating_not_preseason():
    pre = run_elo(schedule(), EloParams()).set_index("game_id")
    # T2 lost in week 1, so its bowl pregame rating must be below its week-1 (preseason) rating.
    assert pre.loc[3, "home_pregame_elo"] < pre.loc[1, "away_pregame_elo"]


def test_bowl_result_does_not_leak_into_regular_season_ratings():
    base = schedule()
    blowout = base.copy()
    blowout.loc[blowout.game_id == 3, ["home_points", "away_points"]] = [0, 45]
    a = run_elo(base, EloParams()).set_index("game_id")
    b = run_elo(blowout, EloParams()).set_index("game_id")
    # Week-2 pregame ratings are identical regardless of what happens in the bowl.
    assert a.loc[2, "away_pregame_elo"] == b.loc[2, "away_pregame_elo"]
    # The following season does see the bowl.
    assert a.loc[4, "home_pregame_elo"] != b.loc[4, "home_pregame_elo"]


def test_season_regression_pulls_toward_baseline():
    p = EloParams(season_regression=0.5)
    pre = run_elo(schedule(), p).set_index("game_id")
    full = run_elo(schedule(), EloParams(season_regression=0.0)).set_index("game_id")
    assert abs(pre.loc[4, "away_pregame_elo"] - 1500) < abs(full.loc[4, "away_pregame_elo"] - 1500)
