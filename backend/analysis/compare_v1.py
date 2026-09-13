"""Compare v2 grades (SQLite) with v1's published results (../4th-down-pipeline/results).

    uv run python -m analysis.compare_v1

Read-only against v1. Writes modeling/reports/v1_vs_v2.json. Joins on CFBD play id; v1 graded
FBS offenses only, so v2 is restricted to FBS offenses for every comparison.
"""

from __future__ import annotations

import glob
import json
import sqlite3

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from app import db, grading
from modeling.config import BACKEND_DIR, REPORTS_DIR

V1_RESULTS = BACKEND_DIR.parents[1] / "4th-down-pipeline" / "results"


def load_v1() -> pd.DataFrame:
    frames = [pd.read_parquet(f) for f in glob.glob(str(V1_RESULTS / "*.parquet"))]
    v1 = pd.concat(frames, ignore_index=True).drop_duplicates("play_id")
    options = v1[["exp_wp_go", "exp_wp_fg", "exp_wp_punt"]].to_numpy()
    v1["v1_recommendation"] = np.array(["go", "field_goal", "punt"])[options.argmax(axis=1)]
    v1["v1_best"] = options.max(axis=1)
    actual = np.select(
        [v1["decision"] == "go", v1["decision"] == "field_goal", v1["decision"] == "punt"],
        [v1["exp_wp_go"], v1["exp_wp_fg"], v1["exp_wp_punt"]],
        np.nan,
    )
    v1["v1_wp_delta"] = actual - v1["v1_best"]
    v1["v1_verdict"] = np.select(
        [
            v1["decision"] == v1["v1_recommendation"],
            v1["v1_wp_delta"].abs() >= grading.MISTAKE_THRESHOLD,
        ],
        ["correct", "mistake"],
        "marginal",
    )
    v1["play_id"] = v1["play_id"].astype(str)
    return v1


def load_v2(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT p.*, g.home_id, g.home_team, g.away_team
           FROM plays_fourth_down p JOIN games g USING (game_id)
           WHERE p.source = 'cfbd'""",
        conn,
    )


def rate_table(df: pd.DataFrame, by: pd.Series, rec_col: str) -> dict:
    return {str(k): round(float(v), 3) for k, v in (df[rec_col] == "go").groupby(by).mean().items()}


def main() -> None:
    v1 = load_v1()
    with db.connect() as conn:
        v2_all = load_v2(conn)
        exclusions = pd.read_sql_query("SELECT play_id, reason FROM exclusions", conn)
    v2 = v2_all[v2_all["offense_classification"] == "fbs"]
    report: dict = {}

    both = v1.merge(v2, on="play_id", suffixes=("_v1", ""))
    v1_only = v1[~v1["play_id"].isin(v2["play_id"])]
    v1_only_reasons = v1_only.merge(exclusions, on="play_id", how="left")["reason"].fillna(
        "not_in_v2_scope_or_play_missing"
    )
    report["coverage"] = {
        "v1_rows": len(v1),
        "v2_graded_all_offenses": len(v2_all),
        "v2_graded_fbs_offense": len(v2),
        "overlap": len(both),
        "v1_only": len(v1_only),
        "v1_only_reasons_in_v2": v1_only_reasons.value_counts().to_dict(),
        "v2_only": int((~v2["play_id"].isin(v1["play_id"])).sum()),
    }

    report["actual_decision_label_agreement"] = round(
        float((both["decision_v1"] == both["decision"]).mean()), 4
    )
    agree = both["v1_recommendation"] == both["recommendation"]
    report["recommendation_agreement"] = {
        "overall": round(float(agree.mean()), 4),
        "by_season": {
            str(k): round(float(v), 3) for k, v in agree.groupby(both["season"]).mean().items()
        },
        "confusion_v1_rows_v2_cols": pd.crosstab(
            both["v1_recommendation"], both["recommendation"]
        ).to_dict(),
    }

    dist_bucket = pd.cut(
        both["distance"], [0, 1, 3, 6, 10, 99], labels=["1", "2-3", "4-6", "7-10", "11+"]
    )
    zone = pd.cut(
        both["yards_to_goal"],
        [0, 20, 40, 60, 80, 99],
        labels=["opp 1-20", "opp 21-40", "midfield 41-60", "own 21-40", "own 1-20"],
    )
    report["go_recommended_rate"] = {
        "overall": {
            "v1": round(float((both["v1_recommendation"] == "go").mean()), 3),
            "v2": round(float((both["recommendation"] == "go").mean()), 3),
            "coaches_actually_went": round(float((both["decision"] == "go").mean()), 3),
        },
        "by_distance": {
            "v1": rate_table(both, dist_bucket, "v1_recommendation"),
            "v2": rate_table(both, dist_bucket, "recommendation"),
        },
        "by_field_zone": {
            "v1": rate_table(both, zone, "v1_recommendation"),
            "v2": rate_table(both, zone, "recommendation"),
        },
    }

    diffs = {}
    for v1c, v2c in (
        ("exp_wp_go", "wp_go"),
        ("exp_wp_fg", "wp_field_goal"),
        ("exp_wp_punt", "wp_punt"),
    ):
        m = both[v2c].notna()
        d = both.loc[m, v2c] - both.loc[m, v1c]
        diffs[v2c] = {
            "n": int(m.sum()),
            "mean_v2_minus_v1": round(float(d.mean()), 4),
            "mean_abs_diff": round(float(d.abs().mean()), 4),
            "correlation": round(float(np.corrcoef(both.loc[m, v2c], both.loc[m, v1c])[0, 1]), 3),
        }
    report["option_wp_differences"] = diffs

    report["verdicts"] = {
        "v1": both["v1_verdict"].value_counts(normalize=True).round(3).to_dict(),
        "v2": both["verdict"].value_counts(normalize=True).round(3).to_dict(),
    }

    # Team-season WP lost (sum of wp_delta), FBS offenses.
    team = both.groupby(["season", "offense_id"]).agg(
        v1=("v1_wp_delta", "sum"), v2=("wp_delta", "sum"), n=("play_id", "size")
    )
    per_season = {}
    for season, t in team.groupby(level="season"):
        rho = spearmanr(t["v1"], t["v2"]).statistic
        per_season[str(season)] = round(float(rho), 3)
    report["team_season_wp_lost_rank_correlation"] = per_season

    t25 = team.loc[2025].copy()
    name_of = v2.assign(
        team=np.where(v2["offense_id"] == v2["home_id"], v2["home_team"], v2["away_team"])
    )
    name_of = name_of.drop_duplicates("offense_id").set_index("offense_id")["team"]
    t25["team"] = t25.index.map(name_of)
    t25["v1_rank"] = t25["v1"].rank()
    t25["v2_rank"] = t25["v2"].rank()
    t25["rank_shift"] = t25["v2_rank"] - t25["v1_rank"]
    report["team_2025_largest_rank_shifts"] = (
        t25.reindex(t25["rank_shift"].abs().sort_values(ascending=False).index)
        .head(8)[["team", "n", "v1", "v2", "v1_rank", "v2_rank"]]
        .round(3)
        .reset_index(drop=True)
        .to_dict("records")
    )

    dis = both[~agree].copy()
    dis["team"] = np.where(dis["offense_id"] == dis["home_id"], dis["home_team"], dis["away_team"])
    dis["opponent"] = np.where(
        dis["offense_id"] == dis["home_id"], dis["away_team"], dis["home_team"]
    )
    dis["v2_margin"] = dis["margin"]
    cols = [
        "season", "week", "team", "opponent", "period", "clock_seconds", "offense_score",
        "defense_score", "distance", "yards_to_goal", "decision", "v1_recommendation",
        "recommendation", "v2_margin", "exp_wp_go", "exp_wp_fg", "exp_wp_punt", "wp_go",
        "wp_field_goal", "wp_punt", "play_text",
    ]  # fmt: skip
    report["largest_disagreements_by_v2_margin"] = (
        dis.sort_values("v2_margin", ascending=False).head(10)[cols].round(3).to_dict("records")
    )

    vandy = both[
        (both["season"] == 2025)
        & (both["distance"] == 4)
        & (both["yards_to_goal"] == 93)
        & ((both["home_team"] == "Missouri") | (both["away_team"] == "Missouri"))
    ]
    report["v1_todo_anomaly_vanderbilt_missouri_2025_4th_and_4_at_93"] = vandy[
        ["play_id", "exp_wp_go", "exp_wp_fg", "exp_wp_punt", "v1_recommendation",
         "p_convert", "wp_go", "wp_punt", "recommendation", "margin", "play_text"]
    ].round(4).to_dict("records")  # fmt: skip

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "v1_vs_v2.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=1, default=str)[:12000])


if __name__ == "__main__":
    main()
