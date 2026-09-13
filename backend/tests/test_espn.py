"""ESPN parsing with obviously fake payloads (team ids 90001 home / 90002 away)."""

from providers import espn

HOME, AWAY = 90001, 90002


def scoreboard(situation: dict, period: int = 3, clock: float = 420.0, state: str = "in") -> dict:
    return {
        "events": [
            {
                "id": "999000001",
                "status": {
                    "clock": clock,
                    "period": period,
                    "type": {"state": state, "shortDetail": "fake"},
                },
                "competitions": [
                    {
                        "neutralSite": False,
                        "situation": situation,
                        "competitors": [
                            {"homeAway": "home", "score": "10", "team": {"id": str(HOME)}},
                            {"homeAway": "away", "score": "3", "team": {"id": str(AWAY)}},
                        ],
                    }
                ],
            }
        ]
    }


def play(
    seq: int,
    down: int,
    team: int,
    ytg: int,
    text: str,
    type_text: str,
    home: int,
    away: int,
    period: int = 3,
    clock: str = "7:00",
    timeout_team: int | None = None,
) -> dict:
    participants = []
    if timeout_team is not None:
        participants = [{"id": str(timeout_team), "timeout": True}]
    return {
        "id": f"9990000010{seq:02d}",
        "sequenceNumber": str(seq),
        "type": {"text": type_text},
        "text": text,
        "homeScore": home,
        "awayScore": away,
        "period": {"number": period},
        "clock": {"displayValue": clock},
        "start": {"down": down, "distance": 3, "yardsToEndzone": ytg, "team": {"id": str(team)}},
        "teamParticipants": participants,
    }


def summary(plays: list[dict], current_team: int | None = None) -> dict:
    drives = {"previous": [{"plays": plays}]}
    if current_team is not None:
        drives["current"] = {"team": {"id": str(current_team)}, "plays": []}
    return {"drives": drives}


def test_yard_line_is_home_relative():
    home_ball = espn.parse_scoreboard(
        scoreboard({"down": 4, "distance": 2, "yardLine": 30, "possession": str(HOME)})
    )[0]
    away_ball = espn.parse_scoreboard(
        scoreboard({"down": 4, "distance": 2, "yardLine": 30, "possession": str(AWAY)})
    )[0]
    home_state, _ = espn.pending_fourth_down(home_ball, None)
    away_state, _ = espn.pending_fourth_down(away_ball, None)
    assert home_state["yards_to_goal"] == 70  # home team at its own 30
    assert away_state["yards_to_goal"] == 30  # away team at the home team's 30
    assert home_state["offense_score"] == 10 and away_state["offense_score"] == 3


def test_null_possession_falls_back_to_current_drive():
    game = espn.parse_scoreboard(scoreboard({"down": 4, "distance": 2, "yardLine": 60}))[0]
    state, why = espn.pending_fourth_down(game, summary([], current_team=AWAY))
    assert (
        why == "ok"
        and state["offense_id"] == AWAY
        and state["offense_source"] == "summary.current_drive"
    )
    missing, why = espn.pending_fourth_down(game, None)
    assert missing is None and why == "offense_unresolved"


def test_pending_timeouts_come_from_timeout_plays_not_the_scoreboard():
    game = espn.parse_scoreboard(
        scoreboard(
            {
                "down": 4,
                "distance": 2,
                "yardLine": 60,
                "possession": str(HOME),
                "homeTimeouts": 0,
                "awayTimeouts": 0,
            }
        )  # fmt: skip
    )[0]
    plays = [
        play(1, 2, HOME, 45, "Timeout Test B, clock 09:00", "Timeout", 10, 3, timeout_team=AWAY),
        # A first-half timeout does not count against the second half.
        play(2, 2, HOME, 45, "Timeout Test A", "Timeout", 10, 3, period=2, timeout_team=HOME),
    ]
    state, _ = espn.pending_fourth_down(game, summary(plays))
    assert (state["offense_timeouts"], state["defense_timeouts"]) == (3, 2)
    assert state["timeouts_source"] == "summary_timeout_plays"


def test_completed_fourth_down_uses_pre_snap_score_and_snap_clock():
    game = espn.parse_scoreboard(scoreboard({}))[0]
    plays = [
        play(1, 3, HOME, 20, "Fake run for 2 yards", "Rush", 10, 3, clock="7:40"),
        # Post-play score on the kick row already includes the 3 points.
        play(2, 4, HOME, 18, "(07:32) Fake 35 yd FG GOOD", "Field Goal Good", 13, 3, clock="7:28"),
    ]
    states = espn.completed_fourth_downs(game, summary(plays))
    assert len(states) == 1
    s = states[0]
    assert (s["offense_score"], s["defense_score"]) == (10, 3)
    assert s["clock_seconds"] == 7 * 60 + 32 and s["clock_source"] == "text_snap"
    assert s["yards_to_goal"] == 18 and s["offense_id"] == HOME


def test_snap_clock_falls_back_to_previous_play_end():
    game = espn.parse_scoreboard(scoreboard({}))[0]
    plays = [
        play(1, 3, AWAY, 50, "Fake pass incomplete", "Pass Incompletion", 10, 3, clock="5:10"),
        play(2, 4, AWAY, 50, "Fake punt 40 yards", "Punt", 10, 3, clock="5:02"),
    ]
    s = espn.completed_fourth_downs(game, summary(plays))[0]
    assert s["clock_seconds"] == 5 * 60 + 10 and s["clock_source"] == "previous_play_end"
