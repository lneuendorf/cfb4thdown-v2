"""Derived views over stored grades: the Punt Index and Week in Review (roadmap Phase 3).

Computed on request from plays_fourth_down, so a regrade or model version bump changes every
aggregate at once and week totals always equal the sum of their games. Scope is FBS offenses.

Definitions (also on the Methodology page):
- Conservative WP lost: -wp_delta summed over plays where the model recommended going for it
  and the coach kicked or punted.
- wp_lost metric: conservative WP lost per game (games = games with a graded fourth down by
  either team). Ranked highest first.
- go_rate metric: share of go recommendations where the team went for it. Ranked lowest first.
- Coach attribution: jobs/coaches.py segments; unattributed team-seasons count for teams only.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from app.api import store

SUBJECTS = ("coach", "team")
METRICS = ("wp_lost", "go_rate")
MOVERS_LIMIT = 5
MOVERS_MIN_GAMES = 3

# Plays by FBS offenses, with the coach whose segment covers the game (NULL if unattributed).
PLAYS_SQL = """
SELECT p.play_id, p.game_id, p.season, p.week, p.season_type, p.offense_id, p.defense_id,
       p.recommendation, p.decision, p.wp_delta, g.start_date,
       CASE WHEN p.offense_id = g.home_id THEN g.home_conference ELSE g.away_conference END
           AS conference,
       cts.coach_id
FROM plays_fourth_down p
JOIN games g ON g.game_id = p.game_id
LEFT JOIN coach_team_seasons cts
  ON cts.team_id = p.offense_id AND cts.season = p.season
 AND g.start_date >= cts.first_game_start AND g.start_date <= cts.last_game_start
WHERE p.offense_classification = 'fbs' AND p.season BETWEEN ? AND ?
"""


def _rows(conn: sqlite3.Connection, season_from: int, season_to: int):
    return conn.execute(PLAYS_SQL, (season_from, season_to)).fetchall()


class _Tally:
    __slots__ = ("games", "fourth_downs", "go_recs", "went_when_rec", "lost", "teams", "seasons")

    def __init__(self) -> None:
        self.games: set[int] = set()
        self.fourth_downs = 0
        self.go_recs = 0
        self.went_when_rec = 0
        self.lost = 0.0
        self.teams: dict[int, str] = {}
        self.seasons: set[int] = set()

    def add(self, r: sqlite3.Row) -> None:
        self.games.add(r["game_id"])
        self.fourth_downs += 1
        self.seasons.add(r["season"])
        self.teams[r["offense_id"]] = r["start_date"]
        if r["recommendation"] == "go":
            self.go_recs += 1
            if r["decision"] == "go":
                self.went_when_rec += 1
            else:
                self.lost += -(r["wp_delta"] or 0.0)

    def value(self, metric: str) -> float | None:
        if metric == "wp_lost":
            return self.lost / len(self.games) if self.games else None
        return self.went_when_rec / self.go_recs if self.go_recs else None

    def latest_team(self) -> int:
        return max(self.teams.items(), key=lambda kv: kv[1])[0]


def _tally(rows, subject: str) -> dict[int, _Tally]:
    out: dict[int, _Tally] = defaultdict(_Tally)
    for r in rows:
        key = r["offense_id"] if subject == "team" else r["coach_id"]
        if key is not None:
            out[key].add(r)
    return out


def _ranked(
    tallies: dict[int, _Tally], metric: str, min_games: int
) -> list[tuple[int, _Tally, float, int | None]]:
    scored = [(k, t, t.value(metric)) for k, t in tallies.items() if t.value(metric) is not None]
    reverse = metric == "wp_lost"
    scored.sort(key=lambda x: (-x[2] if reverse else x[2], -len(x[1].games)))
    out, rank = [], 0
    for key, tally, value in scored:
        qualified = len(tally.games) >= min_games
        if qualified:
            rank += 1
        out.append((key, tally, value, rank if qualified else None))
    # Rows below the minimum stay in the list (greyed out), after the ranked ones.
    return sorted(out, key=lambda x: (x[3] is None, x[3] or 0))


def _coach_names(conn: sqlite3.Connection, ids) -> dict[int, str]:
    ids = [int(i) for i in ids]
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    return {
        r["coach_id"]: f"{r['first_name']} {r['last_name']}".strip()
        for r in conn.execute(f"SELECT * FROM coaches WHERE coach_id IN ({marks})", ids)
    }


def _team_objects(conn: sqlite3.Connection, ids) -> dict[int, dict]:
    teams = store.teams_by_id(conn, ids)
    return {
        i: teams.get(
            i,
            {
                "id": str(i),
                "name": str(i),
                "abbreviation": None,
                "conference": None,
                "logo_url": None,
                "color": None,
            },
        )
        for i in ids
    }


def latest_season(conn: sqlite3.Connection, min_games: int = 0) -> int | None:
    """Most recent season in which some FBS team has at least `min_games` graded games, so the
    default Punt Index isn't an all-greyed-out list in the first weeks of a season."""
    row = conn.execute(
        """SELECT MAX(season) AS s FROM (
             SELECT season, offense_id, COUNT(DISTINCT game_id) AS n FROM plays_fourth_down
             WHERE offense_classification = 'fbs' GROUP BY season, offense_id)
           WHERE n >= ?""",
        (min_games,),
    ).fetchone()
    return row["s"]


def punt_index(
    conn: sqlite3.Connection,
    subject: str,
    metric: str,
    season_from: int,
    season_to: int,
    conference: str | None,
    min_games: int,
    returning: bool,
) -> dict:
    if conference:
        # The team's conference in the season of each play.
        rows = conn.execute(
            f"SELECT * FROM ({PLAYS_SQL}) WHERE conference = ?",
            (season_from, season_to, conference),
        ).fetchall()
    else:
        rows = _rows(conn, season_from, season_to)
    tallies = _tally(rows, subject)
    if subject == "coach" and returning:
        current = conn.execute("SELECT MAX(season) AS s FROM coach_team_seasons").fetchone()["s"]
        active = {
            r["coach_id"]
            for r in conn.execute(
                "SELECT coach_id FROM coach_team_seasons WHERE season = ?", (current,)
            )
        }
        tallies = {k: v for k, v in tallies.items() if k in active}
    ranked = _ranked(tallies, metric, min_games)
    teams = _team_objects(conn, {t.latest_team() for _, t, _, _ in ranked})
    names = _coach_names(conn, [k for k, *_ in ranked]) if subject == "coach" else {}
    return {
        "subject": subject,
        "metric": metric,
        "season_from": season_from,
        "season_to": season_to,
        "conference": conference,
        "min_games": min_games,
        "returning": returning,
        "conferences": _conferences(conn, season_from, season_to),
        "rows": [
            {
                "rank": rank,
                "id": str(key),
                "name": names.get(key, "Unknown coach")
                if subject == "coach"
                else teams[t.latest_team()]["name"],
                "team": teams[t.latest_team()],
                "value": round(value, 4),
                "games": len(t.games),
                "fourth_downs": t.fourth_downs,
                "go_recommendations": t.go_recs,
                "went_for_it": t.went_when_rec,
                "wp_lost_total": round(t.lost, 4),
                "seasons": sorted(t.seasons),
                "sample_warning": rank is None,
            }
            for key, t, value, rank in ranked
        ],
        "unattributed_fourth_downs": sum(1 for r in rows if r["coach_id"] is None)
        if subject == "coach"
        else 0,
    }


def _conferences(conn: sqlite3.Connection, season_from: int, season_to: int) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT home_conference AS c FROM games WHERE season BETWEEN ? AND ?
             AND home_classification = 'fbs' AND home_conference IS NOT NULL
           ORDER BY c""",
        (season_from, season_to),
    )
    return [r["c"] for r in rows]


def punt_index_detail(conn: sqlite3.Connection, subject: str, key: int) -> dict | None:
    bounds = conn.execute(
        "SELECT MIN(season) AS a, MAX(season) AS b FROM plays_fourth_down"
    ).fetchone()
    if bounds["a"] is None:
        return None
    column = "offense_id" if subject == "team" else "coach_id"
    rows = conn.execute(
        f"SELECT * FROM ({PLAYS_SQL}) WHERE {column} = ?", (bounds["a"], bounds["b"], key)
    ).fetchall()
    if not rows:
        return None
    by_season: dict[int, list] = defaultdict(list)
    for r in rows:
        by_season[r["season"]].append(r)
    seasons = []
    for season in sorted(by_season):
        t = _Tally()
        for r in by_season[season]:
            t.add(r)
        # Rank that season among all subjects with the default minimum sample.
        all_rows = _rows(conn, season, season)
        ranked = _ranked(_tally(all_rows, subject), "wp_lost", 6)
        rank = next((rk for k, _, _, rk in ranked if k == key), None)
        seasons.append(
            {
                "season": season,
                "team": _team_objects(conn, [t.latest_team()])[t.latest_team()],
                "games": len(t.games),
                "fourth_downs": t.fourth_downs,
                "go_recommendations": t.go_recs,
                "went_for_it": t.went_when_rec,
                "go_rate": round(t.value("go_rate"), 4) if t.go_recs else None,
                "wp_lost": round(t.value("wp_lost") or 0.0, 4),
                "wp_lost_total": round(t.lost, 4),
                "rank": rank,
                "ranked_of": sum(1 for *_, rk in ranked if rk is not None),
            }
        )
    name = (
        _coach_names(conn, [key]).get(key, "Unknown coach")
        if subject == "coach"
        else seasons[-1]["team"]["name"]
    )
    interim = []
    if subject == "coach":
        interim = [
            r["season"]
            for r in conn.execute(
                "SELECT season FROM coach_team_seasons WHERE coach_id = ? AND is_interim = 1",
                (key,),
            )
        ]
    return {
        "subject": subject,
        "id": str(key),
        "name": name,
        "seasons": seasons,
        "interim_seasons": interim,
    }


# ------------------------------------------------------------------ week in review


def latest_complete_week(conn: sqlite3.Connection) -> tuple[int, str, int] | None:
    rows = conn.execute(
        """SELECT season, season_type, week, MIN(is_final) AS all_final, MAX(start_date) AS last
           FROM games WHERE game_id IN (SELECT DISTINCT game_id FROM plays_fourth_down)
           GROUP BY season, season_type, week ORDER BY last DESC"""
    ).fetchall()
    for r in rows:
        total = conn.execute(
            "SELECT MIN(is_final) AS f FROM games "
            "WHERE season = ? AND season_type = ? AND week = ?",
            (r["season"], r["season_type"], r["week"]),
        ).fetchone()["f"]
        if total:
            return r["season"], r["season_type"], r["week"]
    return None


def week_in_review(
    conn: sqlite3.Connection, season: int, week: int, season_type: str
) -> dict | None:
    games = conn.execute(
        "SELECT * FROM games WHERE season = ? AND week = ? AND season_type = ?",
        (season, week, season_type),
    ).fetchall()
    if not games:
        return None
    game_rows = {g["game_id"]: g for g in games}
    plays = conn.execute(
        """SELECT * FROM plays_fourth_down WHERE season = ? AND week = ? AND season_type = ?
             AND offense_classification = 'fbs'""",
        (season, week, season_type),
    ).fetchall()
    teams = store.teams_by_id(conn, [g["home_id"] for g in games] + [g["away_id"] for g in games])
    mismatched = [p for p in plays if p["decision"] != p["recommendation"]]
    worst = min(plays, key=lambda p: (p["wp_delta"] or 0, p["play_id"]), default=None)
    worst = worst if worst is not None and (worst["wp_delta"] or 0) < 0 else None
    # Best call: followed the model when it said go, with the largest margin over the next option.
    matched_go = [p for p in plays if p["verdict"] == "correct" and p["decision"] == "go"]
    matched = matched_go or [p for p in plays if p["verdict"] == "correct"]
    best = max(matched, key=lambda p: (p["margin"] or 0, p["play_id"]), default=None)

    conf: dict[str, dict] = defaultdict(
        lambda: {"wp_lost": 0.0, "fourth_downs": 0, "followed": 0, "games": set()}
    )
    for p in plays:
        g = game_rows[p["game_id"]]
        name = g["home_conference"] if p["offense_id"] == g["home_id"] else g["away_conference"]
        c = conf[name or "Independent"]
        c["fourth_downs"] += 1
        c["games"].add(p["game_id"])
        if p["decision"] == p["recommendation"]:
            c["followed"] += 1
        else:
            c["wp_lost"] += -(p["wp_delta"] or 0)
    by_conference = sorted(
        (
            {
                "conference": name,
                "wp_lost": round(c["wp_lost"], 4),
                "fourth_downs": c["fourth_downs"],
                "games": len(c["games"]),
                "wp_lost_per_game": round(c["wp_lost"] / len(c["games"]), 4),
                "followed_model_rate": round(c["followed"] / c["fourth_downs"], 4),
            }
            for name, c in conf.items()
        ),
        key=lambda c: -c["wp_lost_per_game"],
    )
    commentary = conn.execute(
        "SELECT body FROM week_commentary WHERE season = ? AND season_type = ? AND week = ?",
        (season, season_type, week),
    ).fetchone()
    graded_games = len({p["game_id"] for p in plays})
    return {
        "season": season,
        "week": week,
        "season_type": season_type,
        "is_complete": all(g["is_final"] for g in games),
        "scope": "fbs_offenses",
        "games_total": len(games),
        "games_graded": graded_games,
        "wp_lost_total": round(-sum(p["wp_delta"] or 0 for p in mismatched), 4),
        "wp_lost_per_game": round(-sum(p["wp_delta"] or 0 for p in mismatched) / graded_games, 4)
        if graded_games
        else None,
        "fourth_downs_total": len(plays),
        "mistakes": sum(1 for p in plays if p["verdict"] == "mistake"),
        "followed_model_rate": round(1 - len(mismatched) / len(plays), 4) if plays else None,
        "worst_call": store.decision_object(worst, game_rows[worst["game_id"]], teams)
        if worst
        else None,
        "best_call": store.decision_object(best, game_rows[best["game_id"]], teams)
        if best
        else None,
        "by_conference": by_conference,
        "punt_index_movers": _movers(conn, season, week, season_type),
        "commentary": commentary["body"] if commentary else None,
    }


def _movers(conn: sqlite3.Connection, season: int, week: int, season_type: str) -> list[dict]:
    """Coaches whose season-to-date Punt Index rank moved most this week (regular season)."""
    if season_type != "regular" or week <= 1:
        return []

    def ranks(through: int) -> dict[int, tuple[int, _Tally]]:
        rows = conn.execute(
            f"SELECT * FROM ({PLAYS_SQL}) WHERE season_type = 'regular' AND week <= ?",
            (season, season, through),
        ).fetchall()
        return {
            k: (rk, t)
            for k, t, _, rk in _ranked(_tally(rows, "coach"), "wp_lost", MOVERS_MIN_GAMES)
            if rk is not None
        }

    now, before = ranks(week), ranks(week - 1)
    moves = [
        (key, rank, before[key][0], t)
        for key, (rank, t) in now.items()
        if key in before and before[key][0] != rank
    ]
    moves.sort(key=lambda m: (-abs(m[2] - m[1]), m[1]))
    moves = moves[:MOVERS_LIMIT]
    names = _coach_names(conn, [m[0] for m in moves])
    teams = _team_objects(conn, {m[3].latest_team() for m in moves})
    return [
        {
            "coach_id": str(key),
            "coach_name": names.get(key, "Unknown coach"),
            "team": teams[t.latest_team()],
            "value": round(t.value("wp_lost") or 0.0, 4),
            "rank_now": rank,
            "rank_before": rank_before,
        }
        for key, rank, rank_before, t in moves
    ]
