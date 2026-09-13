"""Coach attribution by team-season (docs/data-pipeline.md, "Coach attribution").

    uv run python -m jobs.coaches

One CFBD call (/coaches for FIRST_SEASON..current), written to a timestamped raw snapshot.
CFBD lists each coach's games per team-season but no dates, so a mid-season change has no
recorded boundary. The rule, which never guesses:

- One coach listed for the team-season: every game that season is theirs.
- Several coaches: split the team's games in kickoff order, coaches ordered by hire date, but
  only when all of these hold (otherwise the whole team-season is unattributed):
    * the coaches' game counts sum to the team's final games that season;
    * the first coach was hired before the season started;
    * every later coach was hired during the season, no later than their first game
      (plus HIRE_GRACE_DAYS).
  Coaches after the first are flagged is_interim (took over mid-season).

Outputs: coaches, coach_team_seasons (one row per attributed segment with its first and last
game kickoff), coach_attribution_issues (unattributed team-seasons and why).
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd

from app import db
from modeling.cfbd import CFBDClient, fetch_snapshot

LOG = logging.getLogger("coaches")
FIRST_SEASON = 2013
HIRE_GRACE_DAYS = 3
SEASON_START_MONTH = 8  # a hire before August 1 is a preseason hire


def team_games(conn) -> pd.DataFrame:
    frames = []
    for side in ("home", "away"):
        frames.append(
            pd.read_sql_query(
                f"SELECT game_id, season, start_date, is_final, {side}_id AS team_id FROM games "
                "WHERE season >= ?",
                conn,
                params=(FIRST_SEASON,),
            )
        )
    g = pd.concat(frames, ignore_index=True)
    g["start_date"] = pd.to_datetime(g["start_date"], utc=True, format="ISO8601")
    return g.sort_values(["team_id", "season", "start_date", "game_id"]).reset_index(drop=True)


def attribute(
    coach_rows: list[dict], games: pd.DataFrame, current_season: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    coaches, listed = [], []
    for c in coach_rows:
        coaches.append(
            {
                "coach_id": int(c["id"]),
                "first_name": c.get("firstName"),
                "last_name": c.get("lastName"),
                "hire_date": c.get("hireDate"),
            }
        )
        for s in c.get("seasons", []):
            if s.get("teamId") is None or s["year"] < FIRST_SEASON:
                continue
            listed.append(
                {
                    "coach_id": int(c["id"]),
                    "team_id": int(s["teamId"]),
                    "season": int(s["year"]),
                    "games": int(s.get("games") or 0),
                    "hire_date": pd.to_datetime(c.get("hireDate"), utc=True),
                }
            )
    coaches_df = pd.DataFrame(coaches).drop_duplicates("coach_id")
    listed_df = pd.DataFrame(listed)
    segments, issues = [], []
    by_team_season = {k: v for k, v in games.groupby(["team_id", "season"])}
    for (team_id, season), group in listed_df.groupby(["team_id", "season"]):
        team_g = by_team_season.get((team_id, season))
        if team_g is None or team_g.empty:
            continue  # not an in-scope team-season
        finals = team_g[team_g["is_final"].astype(bool)]
        if len(group) == 1:
            row = group.iloc[0]
            span = team_g  # the whole season, including games not yet played
            segments.append(_segment(row, span, 1, False, "sole"))
            continue
        ordered = group.sort_values("hire_date", na_position="first").reset_index(drop=True)
        reason = _split_problem(ordered, finals, season, current_season)
        if reason:
            issues.append({"team_id": team_id, "season": season, "reason": reason,
                           "coaches": len(ordered)})  # fmt: skip
            continue
        start = 0
        for i, row in ordered.iterrows():
            span = finals.iloc[start : start + row["games"]]
            start += row["games"]
            segments.append(_segment(row, span, i + 1, i > 0, "split"))
    return (
        coaches_df,
        pd.DataFrame(segments, columns=SEGMENT_COLUMNS),
        pd.DataFrame(issues, columns=["team_id", "season", "reason", "coaches"]),
    )


SEGMENT_COLUMNS = [
    "coach_id", "team_id", "season", "segment", "games", "first_game_start", "last_game_start",
    "is_interim", "attribution",
]  # fmt: skip


def _segment(row, span: pd.DataFrame, order: int, interim: bool, how: str) -> dict:
    return {
        "coach_id": int(row["coach_id"]),
        "team_id": int(row["team_id"]),
        "season": int(row["season"]),
        "segment": order,
        "games": int(row["games"]),
        "first_game_start": span["start_date"].min().isoformat() if len(span) else None,
        "last_game_start": span["start_date"].max().isoformat() if len(span) else None,
        "is_interim": int(interim),
        "attribution": how,
    }


def _split_problem(ordered: pd.DataFrame, finals: pd.DataFrame, season: int, current: int) -> str:
    if season >= current:
        return "mid_season_change_in_progress"
    if ordered["hire_date"].isna().any():
        return "missing_hire_date"
    if int(ordered["games"].sum()) != len(finals):
        return "games_do_not_sum"
    season_start = pd.Timestamp(year=season, month=SEASON_START_MONTH, day=1, tz="UTC")
    if ordered.loc[0, "hire_date"] >= season_start:
        return "first_coach_hired_in_season"
    start = int(ordered.loc[0, "games"])
    for i in range(1, len(ordered)):
        first_game = finals.iloc[start]["start_date"] if start < len(finals) else None
        hired = ordered.loc[i, "hire_date"]
        if hired < season_start or first_game is None:
            return "hire_dates_inconsistent"
        if hired > first_game + timedelta(days=HIRE_GRACE_DAYS):
            return "hire_dates_inconsistent"
        start += int(ordered.loc[i, "games"])
    return ""


def run(client: CFBDClient | None = None, current_season: int | None = None) -> dict:
    client = client or CFBDClient()
    with db.connect() as conn:
        games = team_games(conn)
        current = current_season or int(games["season"].max())
        rows, path = fetch_snapshot(
            client, "coaches", {"minYear": FIRST_SEASON, "maxYear": current}
        )
        run_id = db.start_run(conn, "coaches", {"max_year": current}, {})
        coaches_df, segments, issues = attribute(rows, games, current)
        conn.execute("DELETE FROM coach_team_seasons")
        conn.execute("DELETE FROM coach_attribution_issues")
        db.upsert_rows(conn, "coaches", coaches_df)
        db.upsert_rows(conn, "coach_team_seasons", segments)
        db.upsert_rows(conn, "coach_attribution_issues", issues)
        counts = {
            "coaches": len(coaches_df),
            "segments": len(segments),
            "split_segments": int((segments["attribution"] == "split").sum()),
            "unattributed_team_seasons": len(issues),
            "issues_by_reason": issues["reason"].value_counts().to_dict() if len(issues) else {},
            "cfbd_calls": client.calls_made,
            "cfbd_remaining": client.last_remaining,
            "raw_snapshot": str(path),
        }
        db.finish_run(conn, run_id, "ok", counts, [])
    LOG.info("coaches: %s", counts)
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run()


if __name__ == "__main__":
    main()
