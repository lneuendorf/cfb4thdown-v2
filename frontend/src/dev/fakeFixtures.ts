// Obviously fake values for the component gallery (CLAUDE.md: never invent stats).
// Team names are fictional, WPs are repeated digits.

import type { Decision, LiveScoreboard, PendingDecision, Team, TickerGame } from "../lib/types";

export const FAKE_HOME: Team = { id: "90001", name: "Fixture State", abbreviation: "FXS", logo_url: null };
export const FAKE_AWAY: Team = { id: "90002", name: "Mock Tech", abbreviation: "MKT", logo_url: null };
export const FAKE_LONG: Team = {
  id: "90003",
  name: "University of Placeholder at Very Long Name",
  abbreviation: "UPVL",
  logo_url: null,
};

const base: Decision = {
  id: "fake-1",
  game_id: "999000001",
  season: 2099,
  week: 1,
  offense: FAKE_HOME,
  defense: FAKE_AWAY,
  period: 2,
  clock: "11:11",
  down: 4,
  distance: 1,
  yard_line: 44,
  yards_to_goal: 44,
  offense_score: 11,
  defense_score: 11,
  recommendation: "go",
  decision: "go",
  confidence: "clear",
  margin: 0.111,
  wp_go: 0.555,
  wp_punt: 0.444,
  wp_field_goal: 0.333,
  wp_delta: 0,
  verdict: "correct",
  outcome: null,
  play_text: "Fake Runner rush for 2 yards (fixture text)",
  is_live: false,
};

export const FAKE_DECISIONS: Decision[] = [
  base,
  {
    ...base,
    id: "fake-2",
    decision: "punt",
    wp_delta: -0.111,
    verdict: "mistake",
    yards_to_goal: 66,
    yard_line: 66,
    wp_field_goal: null,
    play_text: "Fake Punter punt for 44 yards (fixture text)",
  },
  {
    ...base,
    id: "fake-3",
    recommendation: "field_goal",
    decision: "go",
    confidence: "toss_up",
    margin: 0.011,
    wp_delta: -0.011,
    verdict: "marginal",
    distance: 3,
    yards_to_goal: 3,
    yard_line: 3,
    wp_punt: null,
    offense: FAKE_LONG,
    is_live: true,
  },
  {
    ...base,
    id: "fake-4",
    recommendation: "punt",
    decision: "punt",
    confidence: "only_option",
    margin: null,
    wp_go: 0.222,
    wp_punt: 0.333,
    wp_field_goal: null,
    yards_to_goal: 88,
    yard_line: 88,
    distance: 22,
    play_text: null,
  },
];

export const FAKE_PENDING: PendingDecision = {
  game_id: "999000001",
  offense: FAKE_HOME,
  defense: FAKE_AWAY,
  offense_is_home: true,
  home_score: 22,
  away_score: 11,
  period: 4,
  clock: "1:11",
  down: 4,
  distance: 2,
  yard_line: 33,
  yards_to_goal: 33,
  recommendation: "go",
  confidence: "close",
  margin: 0.022,
  wp_go: 0.888,
  wp_punt: null,
  wp_field_goal: 0.866,
};

export const FAKE_TICKER: TickerGame[] = [
  { game_id: "1", away: "MKT", away_score: 11, home: "FXS", home_score: 22, status: "live", period: 4, clock: "1:11", wp_delta_last: -0.111 },
  { game_id: "2", away: "UPVL", away_score: 0, home: "ABC", home_score: 0, status: "live", period: 1, clock: "9:99", wp_delta_last: null },
  { game_id: "3", away: "XYZ", away_score: 33, home: "QRS", home_score: 33, status: "final", period: 4, clock: null, wp_delta_last: 0.022 },
];

export const FAKE_SCOREBOARD: LiveScoreboard = {
  games_live: 2,
  games_total: 3,
  fourth_downs_today: 4,
  wp_lost_today: 0.122,
  followed_model_rate: 0.5,
  pending: FAKE_PENDING,
  decisions: FAKE_DECISIONS,
  ticker: FAKE_TICKER,
};
