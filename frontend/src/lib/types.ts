// Response shapes from docs/api-contract.md.
//
// Where the contract and the built grading layer disagree (docs/grades.md "Conflicts"), these
// types follow the grading layer and the contract has been updated to match:
// - wp_field_goal / wp_punt are null when the option is infeasible;
// - confidence includes "only_option";
// - conference, logo_url, color, week and outcome can be null;
// - pending carries offense_is_home.

export type Option = "go" | "punt" | "field_goal";
export type Verdict = "correct" | "marginal" | "mistake";
export type Confidence = "clear" | "close" | "toss_up" | "only_option";

export interface Meta {
  generated_at: string;
  stale: boolean;
  source: string;
}

export interface Envelope<T> {
  data: T;
  meta: Meta;
}

export interface Team {
  id: string;
  name: string;
  abbreviation: string | null;
  conference?: string | null;
  logo_url?: string | null;
  color?: string | null;
}

export interface OptionWps {
  wp_go: number | null;
  wp_punt: number | null;
  wp_field_goal: number | null;
}

export interface Decision extends OptionWps {
  id: string;
  game_id: string;
  season: number;
  week: number | null;
  offense: Team;
  defense: Team;
  period: number;
  clock: string;
  down: number;
  distance: number;
  yard_line: number;
  yards_to_goal: number;
  offense_score: number;
  defense_score: number;
  recommendation: Option;
  decision: Option;
  confidence?: Confidence | null;
  margin?: number | null;
  wp_delta: number | null;
  verdict: Verdict;
  outcome: string | null;
  play_text: string | null;
  is_live: boolean;
  season_type?: SeasonType;
  source?: "cfbd" | "espn";
  play_type?: string | null;
  clock_source?: string | null;
  timeouts_imputed?: boolean;
  model_version?: string | null;
}

export interface PendingDecision extends OptionWps {
  game_id: string;
  offense: Team;
  defense: Team;
  /** Needed to read home_score/away_score from the offense's side. */
  offense_is_home: boolean;
  home_score: number;
  away_score: number;
  period: number;
  clock: string;
  down: number;
  distance: number;
  yard_line: number;
  yards_to_goal: number;
  recommendation: Option;
  confidence?: Confidence | null;
  margin?: number | null;
}

export interface TickerGame {
  game_id: string;
  away: string | null;
  away_score: number;
  home: string | null;
  home_score: number;
  status: "live" | "final" | "scheduled";
  period: number | null;
  clock: string | null;
  wp_delta_last: number | null;
}

export interface LiveScoreboard {
  games_live: number;
  games_total: number;
  fourth_downs_today: number;
  wp_lost_today: number;
  followed_model_rate: number | null;
  pending: PendingDecision | null;
  decisions: Decision[];
  ticker: TickerGame[];
}

// ---- Phase 2 endpoints (docs/api-contract.md) ----

export type SeasonType = "regular" | "postseason";

export type GradingStatus =
  | "graded"
  | "no_fourth_downs"
  | "failed_quality_gate"
  | "awaiting_plays"
  | "not_final"
  | "not_processed";

export interface GameSummary {
  id: string;
  season: number;
  week: number;
  season_type: SeasonType;
  start_date: string | null;
  status: "final" | "scheduled" | "in_progress";
  neutral_site: boolean;
  home: Team;
  away: Team;
  home_score: number | null;
  away_score: number | null;
  grading_status: GradingStatus;
  fourth_downs: number;
  wp_lost: number;
}

export interface WpPoint {
  period: number;
  clock: string;
  seconds_remaining: number;
  home_wp: number;
  play_id: string | null;
}

export interface GameDetail {
  game: GameSummary;
  grading: { status: GradingStatus; message: string | null };
  wp_series: WpPoint[];
  decisions: Decision[];
  totals: Record<"home" | "away", { fourth_downs: number; wp_delta: number }>;
}

export interface WeekScoreboard extends LiveScoreboard {
  season: number;
  week: number;
  season_type: SeasonType;
  is_complete: boolean;
  games_graded: number;
  wp_lost_per_game: number | null;
  decisions_total: number;
  games: GameSummary[];
}

export interface GamesList {
  season: number;
  week: number;
  season_type: SeasonType;
  games: GameSummary[];
}

export interface TickerFeed {
  games: TickerGame[];
  games_live: number;
}
