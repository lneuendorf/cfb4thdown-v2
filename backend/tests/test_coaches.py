"""Coach attribution rules with obviously fake coaches and games (team 90001, seasons 2098-99)."""

from __future__ import annotations

import pandas as pd

from jobs import coaches

TEAM = 90001


def schedule(season: int, n: int, final: bool = True) -> pd.DataFrame:
    starts = pd.date_range(f"{season}-09-01", periods=n, freq="7D", tz="UTC")
    return pd.DataFrame(
        {"game_id": range(season * 100, season * 100 + n), "season": season,
         "start_date": starts, "is_final": final, "team_id": TEAM}
    )  # fmt: skip


def coach(cid: int, hired: str | None, season: int, games: int) -> dict:
    return {"id": cid, "firstName": "Fake", "lastName": f"Coach{cid}", "hireDate": hired,
            "seasons": [{"teamId": TEAM, "year": season, "games": games}]}  # fmt: skip


def test_single_coach_gets_the_whole_season():
    _, segments, issues = coaches.attribute(
        [coach(1, "2090-01-01", 2098, 12)], schedule(2098, 12), current_season=2099
    )
    assert len(segments) == 1 and issues.empty
    assert segments.iloc[0]["attribution"] == "sole" and not segments.iloc[0]["is_interim"]


def test_mid_season_change_splits_by_hire_date():
    games = schedule(2098, 12)
    interim_first_game = games.iloc[7]["start_date"]
    rows = [
        coach(1, "2090-01-01", 2098, 7),
        coach(2, (interim_first_game - pd.Timedelta(days=2)).isoformat(), 2098, 5),
    ]
    _, segments, issues = coaches.attribute(rows, games, current_season=2099)
    assert issues.empty
    first, second = segments.sort_values("segment").to_dict("records")
    assert (first["games"], second["games"], second["is_interim"]) == (7, 5, 1)
    assert pd.Timestamp(second["first_game_start"]) == interim_first_game


def test_counts_that_dont_sum_are_unattributed():
    rows = [coach(1, "2090-01-01", 2098, 10), coach(2, "2098-10-20", 2098, 10)]
    _, segments, issues = coaches.attribute(rows, schedule(2098, 12), current_season=2099)
    assert segments.empty and issues.iloc[0]["reason"] == "games_do_not_sum"


def test_bowl_coach_with_old_hire_date_is_not_guessed():
    # A later coach whose hire date predates the season (a hire elsewhere) can't be placed.
    rows = [coach(1, "2090-01-01", 2098, 11), coach(2, "2095-01-01", 2098, 1)]
    _, segments, issues = coaches.attribute(rows, schedule(2098, 12), current_season=2099)
    assert (
        segments.empty
        and issues.iloc[0]["reason"] == "first_coach_hired_in_season"
        or (issues.iloc[0]["reason"] == "hire_dates_inconsistent")
    )
