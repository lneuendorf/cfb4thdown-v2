import numpy as np
import pandas as pd

from modeling.build import plays as P
from tests.fixtures import AWAY, HOME, game, play


def build(rows: list[dict], games_rows: list[dict] | None = None) -> pd.DataFrame:
    raw = pd.DataFrame(rows)
    games = pd.DataFrame(games_rows or [game()])
    stats = P.BuildStats()
    df = P.resolve_team_ids(raw, games, stats)
    df = P.order_plays(df)
    df["category"] = P.categorize(df)
    df = P.add_pre_snap_scores(df)
    df = P.fill_stale_clocks(df, {"Rush": 30.0, "Pass Incompletion": 5.0, "default": 20.0}, stats)
    df = df.merge(P.classify_game_clock(df), left_on="game_id", right_index=True, how="left")
    df = P.estimate_snap_clock(df, {"rush": 5.0, "field_goal": 2.0, "default": 5.0})
    return P.fill_timeouts(df, stats)


def test_made_field_goal_is_not_in_its_own_pre_snap_score():
    rows = [
        play(1, HOME, down=3, distance=8, yards_to_goal=20),
        # CFBD reports the post-play score on the kick row itself.
        play(
            2,
            HOME,
            down=4,
            distance=8,
            yards_to_goal=20,
            play_type="Field Goal Good",
            play_text="Fake Kicker 37 yd FG GOOD",
            offense_score_post=3,
        ),
        play(3, AWAY, play_type="Rush", offense_score_post=0, defense_score_post=3),
    ]
    df = build(rows).set_index("play_number")
    assert df.loc[2, "offense_score"] == 0
    assert df.loc[2, "offense_points_on_play"] == 3
    # Next possession: the kicking team is now the defense with 3 points.
    assert df.loc[3, "defense_score"] == 3


def test_offense_not_in_game_is_dropped_not_guessed():
    rows = [play(1, HOME), play(2, "Somebody Else")]
    stats = P.BuildStats()
    df = P.resolve_team_ids(pd.DataFrame(rows), pd.DataFrame([game()]), stats)
    assert len(df) == 1 and stats.counts["rows_unresolved_team"] == 1


def test_text_snap_clock_wins_over_recorded_clock():
    rows = [
        play(1, HOME, clock_raw=600),
        play(2, HOME, clock_raw=590, play_text="(10:00) Fake rush"),
    ]
    df = build(rows).set_index("play_number")
    assert df.loc[2, "clock_seconds"] == 600
    assert df.loc[2, "clock_source"] == "text_snap"


def test_snap_clock_games_use_recorded_clock():
    # After each timeout the next snap is recorded at the timeout's clock: snap-clock recording.
    rows = []
    n = 0
    for clock in (800, 700, 600, 500):
        n += 1
        rows.append(
            play(
                n,
                HOME,
                clock_raw=clock,
                play_type="Timeout",
                play_text=f"Timeout Test A, clock {clock}",
            )
        )
        n += 1
        rows.append(play(n, HOME, clock_raw=clock))
    df = build(rows)
    assert (df["clock_semantics"] == "snap").all()
    scrimmage = df[df["play_type"] == "Rush"]
    assert (scrimmage["clock_seconds"] == scrimmage["clock_raw"]).all()


def test_end_clock_games_add_duration_capped_by_previous_play():
    rows = []
    n = 0
    for clock in (800, 700, 600):
        n += 1
        rows.append(
            play(
                n,
                HOME,
                clock_raw=clock,
                play_type="Timeout",
                play_text=f"Timeout Test A, clock {clock}",
            )
        )
        n += 1
        rows.append(play(n, HOME, clock_raw=clock - 6))  # recorded after the play ran
    n += 1
    rows.append(play(n, HOME, clock_raw=592))  # previous row clock is 594
    df = build(rows)
    assert (df["clock_semantics"] == "end").all()
    last = df.iloc[-1]
    assert last["clock_seconds"] == 594  # 592 + 5s rush duration, capped at previous clock


def test_all_null_timeouts_marked_unknown():
    rows = [play(i, HOME, offense_timeouts_raw=np.nan, defense_timeouts_raw=np.nan) for i in (1, 2)]
    df = build(rows)
    assert not df["timeouts_known"].any()


def test_sporadic_null_timeouts_forward_filled_within_half():
    rows = [
        play(1, HOME, offense_timeouts_raw=2, defense_timeouts_raw=1),
        play(2, HOME, offense_timeouts_raw=np.nan, defense_timeouts_raw=np.nan),
    ]
    df = build(rows).set_index("play_number")
    assert df.loc[2, "offense_timeouts"] == 2 and df.loc[2, "defense_timeouts"] == 1
    assert df["timeouts_known"].all()


def test_score_reconciliation_against_official_final():
    rows = [
        play(1, HOME, offense_score_post=7, play_type="Rushing Touchdown", play_text="Fake TD"),
        play(2, AWAY, offense_score_post=0, defense_score_post=7),
    ]
    df = build(rows)
    assert P.reconcile_scores(df, pd.DataFrame([game(home_points=7, away_points=0)])).iloc[0]
    assert not P.reconcile_scores(df, pd.DataFrame([game(home_points=10, away_points=3)])).iloc[0]


def test_stale_clock_runs_are_interpolated_by_play_type_weight():
    # CFBD repeated 600 across three plays; the next recorded clock is 540.
    rows = [
        play(1, HOME, clock_raw=600, play_type="Rush"),
        play(
            2, HOME, clock_raw=600, play_type="Pass Incompletion", play_text="Fake pass incomplete"
        ),
        play(3, HOME, clock_raw=600, play_type="Rush"),
        play(4, HOME, clock_raw=540, play_type="Rush"),
    ]
    df = build(rows).set_index("play_number")
    # Weights 30, 5, 30 spread the 60 seconds: 600, 600 - 60*30/65, 600 - 60*35/65.
    assert df.loc[1, "clock_filled"] == 600
    assert np.isclose(df.loc[2, "clock_filled"], 600 - 60 * 30 / 65)
    assert np.isclose(df.loc[3, "clock_filled"], 600 - 60 * 35 / 65)
    assert df.loc[4, "clock_filled"] == 540
    assert df.loc[[2, 3], "clock_interpolated"].all() and not df.loc[1, "clock_interpolated"]
    assert (df.loc[[2, 3], "clock_source"] == "interpolated").all()


def test_stale_runs_are_not_evidence_of_snap_clock_recording():
    rows = []
    n = 0
    for clock in (800, 700, 600):
        n += 1
        rows.append(play(n, HOME, clock_raw=clock, play_type="Timeout", play_text="Timeout Test A"))
        for _ in range(3):  # stale: the clock never moves after the timeout
            n += 1
            rows.append(play(n, HOME, clock_raw=clock))
    df = build(rows)
    assert (df["clock_semantics"] != "snap").all()


def test_espn_and_2025_play_types_are_categorized():
    rows = [
        play(1, HOME, down=4, play_type="Punt Return", play_text="Fake punt 40 yds"),
        play(2, HOME, down=2, play_type="Fumble", play_text="Fake fumble"),
    ]
    df = pd.DataFrame(rows)
    assert list(P.categorize(df)) == ["punt", "fumble"]
