"""Pre-snap game states from CFBD play-by-play.

Data fixes relative to v1 (see docs/v1-audit.md, B1/B2/B10/B15):
- Scores: CFBD scores on a play row are post-play. The pre-snap score is the previous row's
  post-play score within the game.
- Clock: CFBD records the snap clock in some games and the end-of-play clock in others. The
  pre-snap clock uses the "(MM:SS)" snap time in the play text when present; otherwise it is
  reconstructed per game (see `estimate_snap_clock`).
- Timeouts: the values on a scrimmage row are pre-snap (timeout rows carry the decrement).
  Nulls are forward-filled per team within the half.
- IDs: offense/defense names are resolved to team ids against that game's two teams only;
  a play whose offense matches neither team is flagged, never guessed.
"""

from __future__ import annotations

import glob
import gzip
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from modeling.config import RAW_DIR

RUSH_TYPES = {"Rush", "Rushing Touchdown"}
PASS_TYPES = {
    "Pass Reception",
    "Pass Incompletion",
    "Passing Touchdown",
    "Pass",
    "Pass Completion",
    "Pass Interception Return",
    "Interception",
    "Pass Interception",
    "Interception Return Touchdown",
    "Sack",
}
# "Fumble" and "Punt Return" appear in 2025 CFBD data and in ESPN live play-by-play.
FUMBLE_TYPES = {
    "Fumble",
    "Fumble Recovery (Own)",
    "Fumble Recovery (Opponent)",
    "Fumble Return Touchdown",
}
PUNT_TYPES = {
    "Punt",
    "Punt Return",
    "Blocked Punt",
    "Punt Return Touchdown",
    "Blocked Punt Touchdown",
}
FG_TYPES = {
    "Field Goal Good",
    "Field Goal Missed",
    "Blocked Field Goal",
    "Blocked Field Goal Touchdown",
    "Missed Field Goal Return",
    "Missed Field Goal Return Touchdown",
}
TURNOVER_TYPES = {
    "Pass Interception Return",
    "Interception",
    "Pass Interception",
    "Interception Return Touchdown",
    "Fumble Recovery (Opponent)",
    "Fumble Return Touchdown",
    "Safety",
}
NON_STATE_TYPES = {
    "Kickoff",
    "Kickoff Return (Offense)",
    "Kickoff Return Touchdown",
    "Timeout",
    "End Period",
    "End of Half",
    "End of Game",
    "End of Regulation",
    "Extra Point Good",
    "Extra Point Missed",
    "Two Point Pass",
    "Two Point Rush",
    "Defensive 2pt Conversion",
    "placeholder",
}
SNAP_TEXT = r"^\((\d{1,2}):(\d{2})\)"
KNEEL_TEXT = r"\bkneel|\bknee\b|\bkneels\b"
SPIKE_TEXT = r"\bspike"


@dataclass
class BuildStats:
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, key: str, n: int) -> None:
        self.counts[key] = self.counts.get(key, 0) + int(n)


def load_raw_plays(season: int) -> pd.DataFrame:
    paths = sorted(glob.glob(str(RAW_DIR / "cfbd" / "plays" / f"*__year={season}.json.gz")))
    rows = []
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            rows.extend(json.load(f))
    return raw_plays_frame(rows)


def raw_plays_frame(rows: list[dict]) -> pd.DataFrame:
    """CFBD /plays rows (from the write-once cache or a current-season snapshot) as a frame."""
    df = pd.DataFrame(rows)
    df = df.rename(
        columns={
            "gameId": "game_id",
            "driveId": "drive_id",
            "id": "play_id",
            "driveNumber": "drive_number",
            "playNumber": "play_number",
            "offenseScore": "offense_score_post",
            "defenseScore": "defense_score_post",
            "offenseTimeouts": "offense_timeouts_raw",
            "defenseTimeouts": "defense_timeouts_raw",
            "yardsToGoal": "yards_to_goal",
            "yardsGained": "yards_gained",
            "playType": "play_type",
            "playText": "play_text",
        }
    )
    df["clock_raw"] = df["clock"].map(lambda c: c["minutes"] * 60 + c["seconds"])
    df["play_text"] = df["play_text"].fillna("")
    df["play_id_num"] = df["play_id"].astype("int64")
    return df.drop(columns=["clock"]).drop_duplicates("play_id")


def categorize(df: pd.DataFrame) -> pd.Series:
    t, text = df["play_type"], df["play_text"]
    kneel = text.str.contains(KNEEL_TEXT, case=False, regex=True)
    spike = text.str.contains(SPIKE_TEXT, case=False, regex=True)
    return pd.Series(
        np.select(
            [
                t.isin(NON_STATE_TYPES) | (df["down"] < 1) | (df["down"] > 4),
                t.eq("Penalty"),
                t.isin(PUNT_TYPES),
                t.isin(FG_TYPES),
                kneel & (t.isin(RUSH_TYPES) | t.isin(FUMBLE_TYPES)),
                spike & t.isin(PASS_TYPES),
                t.isin(RUSH_TYPES),
                t.isin(PASS_TYPES),
                t.isin(FUMBLE_TYPES),
                t.eq("Safety"),
            ],
            [
                "non_state",
                "penalty",
                "punt",
                "field_goal",
                "kneel",
                "spike",
                "rush",
                "pass",
                "fumble",
                "safety",
            ],
            default="other",
        ),
        index=df.index,
    )


def order_plays(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["game_id", "drive_number", "play_number", "play_id_num"]).reset_index(
        drop=True
    )


def resolve_team_ids(df: pd.DataFrame, games: pd.DataFrame, stats: BuildStats) -> pd.DataFrame:
    g = games[["game_id", "home_id", "away_id", "home_team", "away_team"]]
    df = df.merge(g, on="game_id", how="inner")
    offense_is_home = df["offense"] == df["home_team"]
    offense_is_away = df["offense"] == df["away_team"]
    defense_ok = np.where(
        offense_is_home, df["defense"] == df["away_team"], df["defense"] == df["home_team"]
    )
    resolved = (offense_is_home ^ offense_is_away) & defense_ok
    stats.add("rows_unresolved_team", (~resolved).sum())
    df = df[resolved].copy()
    df["offense_is_home"] = (df["offense"] == df["home_team"]).to_numpy()
    df["offense_id"] = np.where(df["offense_is_home"], df["home_id"], df["away_id"])
    df["defense_id"] = np.where(df["offense_is_home"], df["away_id"], df["home_id"])
    return df


def add_pre_snap_scores(df: pd.DataFrame) -> pd.DataFrame:
    home_post = np.where(df["offense_is_home"], df["offense_score_post"], df["defense_score_post"])
    away_post = np.where(df["offense_is_home"], df["defense_score_post"], df["offense_score_post"])
    df["home_score_post"], df["away_score_post"] = home_post, away_post
    # Previous row's post-play score. Measured against alternatives (running max, previous
    # state row) this agrees best with non-scoring plays leaving the score unchanged (98.5-99.1%
    # in 2022-2025). Rows where the score then decreases are flagged invalid in build_season.
    g = df.groupby("game_id", sort=False)
    df["home_score_pre"] = g["home_score_post"].shift(1).fillna(0)
    df["away_score_pre"] = g["away_score_post"].shift(1).fillna(0)
    df["offense_score"] = np.where(
        df["offense_is_home"], df["home_score_pre"], df["away_score_pre"]
    )
    df["defense_score"] = np.where(
        df["offense_is_home"], df["away_score_pre"], df["home_score_pre"]
    )
    df["offense_points_on_play"] = df["offense_score_post"] - df["offense_score"]
    df["defense_points_on_play"] = df["defense_score_post"] - df["defense_score"]
    return df


def reconcile_scores(df: pd.DataFrame, games: pd.DataFrame) -> pd.Series:
    """Per game: does the highest play-by-play score equal the official final score?"""
    recon = df.groupby("game_id", sort=False)[["home_score_post", "away_score_post"]].max()
    recon = recon.join(games.set_index("game_id")[["home_points", "away_points"]])
    return (recon["home_score_post"] == recon["home_points"]) & (
        recon["away_score_post"] == recon["away_points"]
    )


SCRIMMAGE_CATEGORIES = [
    "rush",
    "pass",
    "fumble",
    "punt",
    "field_goal",
    "kneel",
    "spike",
    "safety",
    "other",
]
CLEAN_CLOCK_MAX_REPEAT_SHARE = 0.03


def clock_repeat_share(df: pd.DataFrame) -> pd.Series:
    """Per game: share of rush/pass plays whose next scrimmage play has the identical clock."""
    s = df[df["category"].isin(SCRIMMAGE_CATEGORIES) & df["period"].between(1, 4)]
    g = s.groupby("game_id", sort=False)
    repeat = (g["clock_raw"].shift(-1) == s["clock_raw"]) & (g["period"].shift(-1) == s["period"])
    return repeat[s["category"].isin(["rush", "pass"])].groupby(s["game_id"]).mean()


def estimate_interpolation_weights(frames: list[pd.DataFrame]) -> dict[str, float]:
    """Median game-clock seconds from a play's recorded clock to the next play's, by play type.

    Measured only on games whose clocks update every play (repeat share under 3%).
    """
    parts = []
    for df in frames:
        share = clock_repeat_share(df)
        clean = df[df["game_id"].isin(share[share < CLEAN_CLOCK_MAX_REPEAT_SHARE].index)]
        s = clean[
            clean["category"].isin(SCRIMMAGE_CATEGORIES + ["penalty"])
            & clean["period"].between(1, 4)
        ]
        g = s.groupby("game_id", sort=False)
        elapsed = (s["clock_raw"] - g["clock_raw"].shift(-1)).where(
            g["period"].shift(-1) == s["period"]
        )
        ok = elapsed.between(0, 60)
        parts.append(pd.DataFrame({"play_type": s.loc[ok, "play_type"], "elapsed": elapsed[ok]}))
    all_parts = pd.concat(parts, ignore_index=True)
    weights = all_parts.groupby("play_type")["elapsed"].median().to_dict()
    weights["default"] = float(all_parts["elapsed"].median())
    return {k: float(v) for k, v in weights.items()}


def fill_stale_clocks(
    df: pd.DataFrame, weights: dict[str, float], stats: BuildStats
) -> pd.DataFrame:
    """Interpolate clocks CFBD repeated across consecutive scrimmage plays.

    In 2013-2023 roughly half of plays carry the previous play's clock (the clock only updated
    intermittently). Every play takes time, so identical clocks on consecutive scrimmage plays
    are stale. Within each run the first clock is kept and later plays are spaced toward the
    next recorded clock, weighted by how much clock their play type typically uses. Simulated
    on clean 2024-25 games: MAE 9.9s on affected plays, versus 84s with the stale values.
    """
    df["clock_filled"] = df["clock_raw"].astype(float)
    df["clock_interpolated"] = False
    scrim = df["category"].isin(SCRIMMAGE_CATEGORIES) & df["period"].between(1, 5)
    default_w = weights.get("default", 20.0)
    filled = df["clock_filled"].to_numpy().copy()
    interpolated = np.zeros(len(df), dtype=bool)
    wts_all = df["play_type"].map(weights).fillna(default_w).clip(lower=1.0).to_numpy()
    sub = df[scrim]
    positions = np.flatnonzero(scrim.to_numpy())
    for idx in sub.groupby(["game_id", "period"], sort=False).indices.values():
        rows = positions[idx]
        clocks = filled[rows]
        k = 0
        while k < len(rows):
            j = k
            while j + 1 < len(rows) and clocks[j + 1] == clocks[k]:
                j += 1
            if j > k:
                w = wts_all[rows[k : j + 1]]
                end = clocks[j + 1] if j + 1 < len(rows) else max(clocks[k] - w.sum(), 0.0)
                cum = np.concatenate([[0.0], np.cumsum(w)[:-1]]) / w.sum()
                filled[rows[k : j + 1]] = clocks[k] - (clocks[k] - end) * cum
                interpolated[rows[k + 1 : j + 1]] = True
            k = j + 1
    df["clock_filled"] = filled
    df["clock_interpolated"] = interpolated
    stats.add("rows_clock_interpolated", interpolated.sum())
    return df


def classify_game_clock(df: pd.DataFrame) -> pd.Series:
    """Per game: 'snap' if recorded clocks are snap times, 'end' if end-of-play, else 'unknown'.

    Evidence: the clock is stopped during a timeout, so the next snap happens at the timeout's
    clock. A following scrimmage play recorded at that same clock means snap-clock recording.
    Plays inside stale-clock runs are not evidence (their clock simply never updated).
    """
    g = df.groupby("game_id", sort=False)
    prev_type = g["play_type"].shift(1)
    prev_clock = g["clock_raw"].shift(1)
    prev_period = g["period"].shift(1)
    stale = (
        df["clock_interpolated"].astype(bool)
        if "clock_interpolated" in df
        else pd.Series(False, index=df.index)
    )
    nxt_same = (g["clock_raw"].shift(-1) == df["clock_raw"]) & (
        g["period"].shift(-1) == df["period"]
    )
    after_timeout = (
        prev_type.eq("Timeout")
        & (prev_period == df["period"])
        & df["category"].isin(["rush", "pass", "punt", "field_goal", "fumble"])
        & ~stale
        & ~nxt_same
    )
    ev = pd.DataFrame(
        {
            "game_id": df["game_id"],
            "equal": (df["clock_raw"] == prev_clock) & after_timeout,
            "evidence": after_timeout,
        }
    )
    agg = ev.groupby("game_id").agg(n=("evidence", "sum"), eq=("equal", "sum"))
    share = agg["eq"] / agg["n"].where(agg["n"] > 0)
    label = np.select(
        [agg["n"] < 3, share >= 0.7, share <= 0.3], ["unknown", "snap", "end"], "unknown"
    )
    return pd.Series(label, index=agg.index, name="clock_semantics")


def estimate_snap_clock(df: pd.DataFrame, durations: dict[str, float]) -> pd.DataFrame:
    """Pre-snap clock (seconds left in period) and how it was obtained."""
    m = df["play_text"].str.extract(SNAP_TEXT)
    text_clock = m[0].astype(float) * 60 + m[1].astype(float)
    text_clock = text_clock.where(text_clock <= 900)
    if "clock_filled" not in df:
        df["clock_filled"] = df["clock_raw"].astype(float)
        df["clock_interpolated"] = False
    clock = df["clock_filled"]
    g = df.groupby("game_id", sort=False)
    prev_clock = g["clock_filled"].shift(1).where(g["period"].shift(1) == df["period"])
    cap = prev_clock.fillna(900.0)
    dur = df["category"].map(durations).fillna(durations.get("default", 5.0))
    end_estimate = np.minimum(clock + dur, cap)
    unknown_estimate = np.minimum(clock + dur / 2, cap)
    sem = df["clock_semantics"]
    interp = df["clock_interpolated"].astype(bool)
    conditions = [text_clock.notna(), interp, sem.eq("snap"), sem.eq("end")]
    df["clock_seconds"] = np.select(
        conditions, [text_clock, clock, clock, end_estimate], default=unknown_estimate
    )
    df["clock_source"] = np.select(
        conditions,
        ["text_snap", "interpolated", "recorded_snap", "end_plus_duration"],
        default="unknown_plus_half_duration",
    )
    df["snap_clock_text"] = text_clock
    return df


def fill_timeouts(df: pd.DataFrame, stats: BuildStats) -> pd.DataFrame:
    home_to = np.where(
        df["offense_is_home"], df["offense_timeouts_raw"], df["defense_timeouts_raw"]
    )
    away_to = np.where(
        df["offense_is_home"], df["defense_timeouts_raw"], df["offense_timeouts_raw"]
    )
    df["half"] = np.where(df["period"] <= 2, 1, 2)
    tmp = pd.DataFrame(
        {"game_id": df["game_id"], "half": df["half"], "home": home_to, "away": away_to}
    )
    stats.add("timeouts_null_rows", tmp["home"].isna().sum())
    # Games with no timeout values at all (54 in 2025, none with timeout rows to rebuild from)
    # are marked unknown rather than filled with 3s.
    known = tmp.groupby("game_id", sort=False)["home"].transform(lambda s: s.notna().any())
    df["timeouts_known"] = known.to_numpy()
    stats.add("games_timeouts_unknown", (~known).groupby(tmp["game_id"]).any().sum())
    filled = tmp.groupby(["game_id", "half"], sort=False)[["home", "away"]].ffill().fillna(3)
    home_f, away_f = filled["home"].clip(0, 3), filled["away"].clip(0, 3)
    df["offense_timeouts"] = np.where(df["offense_is_home"], home_f, away_f)
    df["defense_timeouts"] = np.where(df["offense_is_home"], away_f, home_f)
    df["timeouts_imputed"] = tmp["home"].isna().to_numpy()
    return df


def add_next_state(df: pd.DataFrame) -> pd.DataFrame:
    """For each state row: the next state row's offense, yards to goal, down and half."""
    is_state = df["category"] != "non_state"
    st = df.loc[is_state, ["game_id", "offense_id", "yards_to_goal", "down", "half"]]
    g = st.groupby("game_id", sort=False)
    nxt = pd.DataFrame(
        {
            "next_offense_id": g["offense_id"].shift(-1),
            "next_yards_to_goal": g["yards_to_goal"].shift(-1),
            "next_down": g["down"].shift(-1),
            "next_half": g["half"].shift(-1),
        },
        index=st.index,
    )
    return df.join(nxt)


def prepare_season(
    season: int, games: pd.DataFrame, stats: BuildStats, raw: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Raw plays for final in-scope games, team ids resolved, ordered and categorized.

    `raw` defaults to the season's write-once cache; current-season jobs pass snapshot rows.
    """
    raw = load_raw_plays(season) if raw is None else raw
    stats.add("raw_rows", len(raw))
    final = games[games["is_final"] & (games["season"] == season)]
    raw = raw[raw["game_id"].isin(final["game_id"])]
    stats.add("rows_in_final_games", len(raw))
    df = resolve_team_ids(raw, final, stats)
    df = order_plays(df)
    df["category"] = categorize(df)
    return df


def build_season(
    season: int,
    games: pd.DataFrame,
    durations: dict[str, float],
    interpolation_weights: dict[str, float],
    raw: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, BuildStats]:
    stats = BuildStats()
    final = games[games["is_final"] & (games["season"] == season)]
    df = prepare_season(season, games, stats, raw)
    df = add_pre_snap_scores(df)
    df = fill_stale_clocks(df, interpolation_weights, stats)
    sem = classify_game_clock(df)
    df = df.merge(sem, left_on="game_id", right_index=True, how="left")
    df = estimate_snap_clock(df, durations)
    df = fill_timeouts(df, stats)
    df = add_next_state(df)

    score_down = (df["offense_points_on_play"] < 0) | (df["defense_points_on_play"] < 0)
    stats.add("rows_score_decrease", score_down.sum())
    ok = reconcile_scores(df, final)
    df["score_reconciled"] = df["game_id"].map(ok).fillna(False).astype(bool)
    stats.add("games", len(ok))
    stats.add("games_score_not_reconciled", (~ok).sum())
    # Per-game scoring consistency: non-scoring scrimmage plays should not change the score.
    # 2013 often types touchdowns as plain "Rush"/"Pass" with TOUCHDOWN only in the text.
    scoring_text = df["play_text"].str.contains(r"touchdown|\bTD\b|safety", case=False, regex=True)
    nonscoring = (
        df["category"].isin(["rush", "pass", "punt", "penalty", "kneel", "spike"])
        & ~df["play_type"].str.contains("Touchdown", regex=False)
        & ~scoring_text
        & df["period"].between(1, 4)
    )
    unchanged = (df["offense_points_on_play"] == 0) & (df["defense_points_on_play"] == 0)
    consistency = unchanged[nonscoring].groupby(df.loc[nonscoring, "game_id"]).mean()
    df["score_consistency"] = df["game_id"].map(consistency).fillna(0.0)
    df["training_eligible_game"] = df["score_reconciled"] & (df["score_consistency"] >= 0.95)
    stats.add(
        "games_training_eligible",
        df.drop_duplicates("game_id")["training_eligible_game"].sum(),
    )
    df["distance_raw"] = df["distance"]
    df.loc[df["distance"] == 0, "distance"] = 1
    df["distance"] = np.minimum(df["distance"], df["yards_to_goal"])
    df["valid_state"] = (
        (df["category"] != "non_state")
        & df["period"].between(1, 4)
        & df["down"].between(1, 4)
        & df["yards_to_goal"].between(1, 99)
        & (df["distance"] >= 1)
        & df["clock_seconds"].between(0, 900)
        & (df["offense_score"] >= 0)
        & (df["defense_score"] >= 0)
        & ~score_down
    )
    stats.add("state_rows", (df["category"] != "non_state").sum())
    stats.add("valid_state_rows", df["valid_state"].sum())
    stats.add("overtime_state_rows", ((df["category"] != "non_state") & (df["period"] > 4)).sum())
    return df, stats


def estimate_play_durations(
    seasons: list[int], games: pd.DataFrame, interpolation_weights: dict[str, float]
) -> dict[str, float]:
    """Median seconds between snap (text timestamp) and recorded clock, by play category.

    Uses only games classified as end-of-play recorders and rows whose text carries a snap time.
    """
    samples = []
    for season in seasons:
        df = prepare_season(season, games, BuildStats())
        df = fill_stale_clocks(df, interpolation_weights, BuildStats())
        df = df[~df["clock_interpolated"]]
        df = df.merge(classify_game_clock(df), left_on="game_id", right_index=True)
        m = df["play_text"].str.extract(SNAP_TEXT)
        snap = m[0].astype(float) * 60 + m[1].astype(float)
        diff = snap - df["clock_raw"]
        ok = snap.notna() & diff.between(0, 60) & (df["clock_semantics"] != "snap")
        samples.append(pd.DataFrame({"category": df.loc[ok, "category"], "diff": diff[ok]}))
    s = pd.concat(samples)
    durations = s.groupby("category")["diff"].median().to_dict()
    durations["default"] = float(s["diff"].median())
    return {k: float(v) for k, v in durations.items()}
