// Display formatting at the edge (docs/api-contract.md: the API sends raw floats).
// Copy rules from docs/design-spec.md: WP to one decimal, rates to whole percents, signed
// deltas with a true minus sign.

import type { Confidence, Option, Team, Verdict } from "./types";

const MINUS = "−";

/** 0.4123 → "41.2%". Null → "—". */
export function formatWp(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

/** −0.094 → "−9.4%", 0.052 → "+5.2%", 0 → "0.0%". */
export function formatDelta(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const points = Math.round(value * 1000) / 10;
  if (points === 0) return "0.0%";
  return `${points < 0 ? MINUS : "+"}${Math.abs(points).toFixed(1)}%`;
}

/** 0.644 → "64%". */
export function formatRate(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

export function formatPeriod(period: number | null | undefined): string {
  if (period == null || period <= 0) return "";
  return period <= 4 ? `Q${period}` : period === 5 ? "OT" : `${period - 4}OT`;
}

const OPTION_LABELS: Record<Option, string> = {
  go: "Go for it",
  punt: "Punt",
  field_goal: "Field goal",
};

const OPTION_SHORT: Record<Option, string> = { go: "Go", punt: "Punt", field_goal: "FG" };

export const optionLabel = (option: Option) => OPTION_LABELS[option];
export const optionShort = (option: Option) => OPTION_SHORT[option];

const CONFIDENCE_LABELS: Record<Confidence, string> = {
  clear: "Clear call",
  close: "Close call",
  toss_up: "Toss-up",
  only_option: "Only option",
};

export const confidenceLabel = (c: Confidence) => CONFIDENCE_LABELS[c];

const VERDICT_LABELS: Record<Verdict, string> = {
  correct: "Matched model",
  marginal: "Marginal miss",
  mistake: "Model disagreed",
};

export const verdictLabel = (v: Verdict) => VERDICT_LABELS[v];

export function teamLabel(team: Team): string {
  return team.abbreviation ?? team.name;
}

/** "4th & 2 at TTU 38", "4th & goal at TTU 3", "4th & 10 at ORST 20", "4th & 5 at 50". */
export function situation(
  down: number,
  distance: number,
  yardsToGoal: number,
  offense: Team,
  defense: Team,
): string {
  const ordinal = ["", "1st", "2nd", "3rd", "4th"][down] ?? `${down}th`;
  const toGo = distance >= yardsToGoal ? "goal" : String(distance);
  let spot: string;
  if (yardsToGoal === 50) spot = "50";
  else if (yardsToGoal > 50) spot = `${teamLabel(offense)} ${100 - yardsToGoal}`;
  else spot = `${teamLabel(defense)} ${yardsToGoal}`;
  return `${ordinal} & ${toGo} at ${spot}`;
}
