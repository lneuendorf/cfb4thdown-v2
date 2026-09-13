import numpy as np
import pandas as pd

from app import grading


def options(rows: list[tuple[float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["wp_go", "wp_field_goal", "wp_punt"])


def test_recommendation_ignores_infeasible_options_and_labels_confidence():
    opts = options(
        [(0.40, np.nan, 0.30), (0.50, 0.49, 0.30), (0.50, 0.47, 0.30), (0.2, np.nan, np.nan)]
    )
    rec = grading.recommend(opts)
    assert list(rec["recommendation"]) == ["go", "go", "go", "go"]
    assert np.allclose(rec["margin"].iloc[:3], [0.10, 0.01, 0.03])
    assert list(rec["confidence"]) == ["clear", "toss_up", "close", "only_option"]


def test_verdicts_use_the_single_threshold():
    opts = options(
        [(0.50, 0.40, 0.44), (0.50, 0.49, 0.30), (0.50, 0.49, 0.30), (0.50, 0.40, np.nan)]
    )
    decision = pd.Series(["punt", "field_goal", "go", "punt"])
    rec = grading.recommend(opts)
    g = grading.grade(decision, opts, rec)
    assert list(g["verdict"]) == ["mistake", "marginal", "correct", "ungraded"]
    assert np.isclose(g["wp_delta"].iloc[0], -0.06)
    assert g["wp_delta"].iloc[2] == 0.0
    assert (g["wp_delta"].dropna() <= 0).all()


def test_garbage_time_needs_both_late_and_lopsided():
    gsr = pd.Series([200, 200, 1200])
    wp = pd.Series([0.995, 0.6, 0.999])
    assert list(grading.is_garbage_time(gsr, wp)) == [True, False, False]
