import numpy as np

from modeling.features import add_state_features, flip_possession, kneelout_seconds_remaining
from tests.fixtures import state


def test_kneelout_has_no_two_minute_warning():
    # 1st down, 125s left, defense has no timeouts: four kneels with three 40s runoffs.
    left = kneelout_seconds_remaining(np.array([125.0]), np.array([0]), np.array([1]))
    assert left[0] == 0
    # v1's NFL two-minute-warning rule would have stopped the clock at 120.
    left = kneelout_seconds_remaining(np.array([170.0]), np.array([0]), np.array([1]))
    assert left[0] == 170 - 4 * 2 - 3 * 40


def test_defensive_timeouts_stop_runoff():
    no_to = kneelout_seconds_remaining(np.array([200.0]), np.array([0]), np.array([1]))
    three = kneelout_seconds_remaining(np.array([200.0]), np.array([3]), np.array([1]))
    assert three[0] - no_to[0] == 3 * 40


def test_distance_capped_at_yards_to_goal():
    df = add_state_features(state(yards_to_goal=3, distance=10))
    assert df["distance"].iloc[0] == 3


def test_time_features():
    df = add_state_features(state(period=3, clock_seconds=300))
    assert df["game_seconds_remaining"].iloc[0] == 900 + 300
    assert df["seconds_left_in_half"].iloc[0] == 900 + 300
    assert np.isclose(df["pct_game_played"].iloc[0], 1 - 1200 / 3600)


def test_flip_possession_swaps_perspective():
    s = state(offense_score=10, defense_score=3, home_indicator=1, offense_spread=-7.0)
    f = flip_possession(s)
    assert (f["offense_score"].iloc[0], f["defense_score"].iloc[0]) == (3, 10)
    assert f["home_indicator"].iloc[0] == -1 and f["offense_spread"].iloc[0] == 7.0
    assert add_state_features(f)["elo_diff"].iloc[0] == -add_state_features(s)["elo_diff"].iloc[0]
