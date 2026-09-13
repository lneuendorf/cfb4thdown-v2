import numpy as np
import pandas as pd
import pytest

from modeling import inference, options
from modeling.config import ARTIFACTS_DIR
from tests.fixtures import state

needs_artifacts = pytest.mark.skipif(
    not all((ARTIFACTS_DIR / n / v).exists() for n, v in inference.MODEL_VERSIONS.items())
    or not (ARTIFACTS_DIR / "decision_assumptions" / options.ASSUMPTIONS_VERSION).exists(),
    reason="model artifacts not trained",
)


@needs_artifacts
def test_option_feasibility_follows_model_scope():
    states = pd.concat(
        [state(yards_to_goal=70, distance=5), state(yards_to_goal=20, distance=5)],
        ignore_index=True,
    )
    res = options.evaluate_options(states)
    assert np.isnan(res.loc[0, "wp_field_goal"]) and not np.isnan(res.loc[0, "wp_punt"])
    assert np.isnan(res.loc[1, "wp_punt"]) and not np.isnan(res.loc[1, "wp_field_goal"])
    wp_cols = ["wp_go", "wp_field_goal", "wp_punt", "wp_convert", "wp_fail"]
    values = res[wp_cols].to_numpy()
    assert np.all((values[~np.isnan(values)] >= 0) & (values[~np.isnan(values)] <= 1))


@needs_artifacts
def test_expiring_clock_is_resolved_by_the_score():
    # Up 3 with 2 seconds left: any option that runs the clock out wins.
    s = state(period=4, clock_seconds=2, offense_score=24, defense_score=21, yards_to_goal=60)
    res = options.evaluate_options(s)
    assert res.loc[0, "wp_punt"] == 1.0
    assert res.loc[0, "wp_fail"] == 1.0


@needs_artifacts
def test_goal_to_go_conversion_is_a_touchdown():
    tied = options.evaluate_options(
        state(yards_to_goal=2, distance=2, offense_score=7, defense_score=7)
    )
    # Converting from the 2 is a TD: better than a failed attempt and than a made field goal.
    assert tied.loc[0, "wp_convert"] > tied.loc[0, "wp_fg_made"] > tied.loc[0, "wp_fail"]


@needs_artifacts
def test_better_field_position_never_hurts_going_for_it():
    near = options.evaluate_options(state(yards_to_goal=35, distance=2))
    far = options.evaluate_options(state(yards_to_goal=75, distance=2))
    assert near.loc[0, "wp_go"] > far.loc[0, "wp_go"]
