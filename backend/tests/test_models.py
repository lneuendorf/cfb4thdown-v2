"""Artifact checks: loadable from JSON, train/serve parity, and directional sanity."""

import numpy as np
import pytest
from scipy.stats import norm

from modeling import inference
from modeling.config import ARTIFACTS_DIR
from modeling.train.field_goal import mills
from tests.fixtures import state

needs_artifacts = pytest.mark.skipif(
    not all((ARTIFACTS_DIR / n / v).exists() for n, v in inference.MODEL_VERSIONS.items()),
    reason="model artifacts not trained",
)


def test_mills_ratio_uses_linear_index():
    # v1 passed a probability here; the linear index of 0 must give phi(0)/Phi(0).
    assert np.isclose(mills(np.array([0.0]))[0], norm.pdf(0) / 0.5)


@needs_artifacts
def test_every_artifact_declares_features_and_version():
    for name, version in inference.MODEL_VERSIONS.items():
        a = inference.artifact(name)
        assert a.metadata["version"] == version
        assert a.metadata.get("features") or a.metadata.get("outcome_features")


@needs_artifacts
def test_wp_directional_sanity():
    ahead = inference.win_probability(
        state(period=4, clock_seconds=60, offense_score=21, defense_score=7)
    )
    behind = inference.win_probability(
        state(period=4, clock_seconds=60, offense_score=7, defense_score=21)
    )
    assert ahead[0] > 0.97 and behind[0] < 0.03
    near = inference.win_probability(state(down=1, distance=10, yards_to_goal=5))
    far = inference.win_probability(state(down=1, distance=10, yards_to_goal=95))
    assert near[0] > far[0]


@needs_artifacts
def test_conversion_decreases_with_distance():
    p = [inference.conversion_probability(state(distance=d))[0] for d in (1, 3, 6, 10)]
    assert p == sorted(p, reverse=True)
    assert 0.55 < p[0] < 0.85


@needs_artifacts
def test_field_goal_decreases_with_distance():
    p = [
        inference.field_goal_make_probability(state(yards_to_goal=y, distance=min(y, 5)))[0]
        for y in (5, 20, 35, 45)
    ]
    assert p == sorted(p, reverse=True)
    assert p[0] > 0.9 and p[-1] < 0.6


@needs_artifacts
def test_punt_pins_deeper_from_closer_spots():
    from_own_20 = inference.punt_receiving_yards_to_goal(state(yards_to_goal=80))[0]
    from_opp_40 = inference.punt_receiving_yards_to_goal(state(yards_to_goal=40))[0]
    assert from_opp_40 > from_own_20
    assert 75 < from_opp_40 < 95
