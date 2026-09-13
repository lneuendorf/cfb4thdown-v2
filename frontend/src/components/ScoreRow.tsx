import type { Team } from "../lib/types";
import { TeamMark } from "./TeamMark";

interface ScoreRowProps {
  team: Team;
  score: number;
  opponentScore: number;
  size?: 30 | 34 | 44;
}

/** Leading score is the bulb, trailing is muted, tied is plain text. */
export function ScoreRow({ team, score, opponentScore, size = 30 }: ScoreRowProps) {
  const tone = score > opponentScore ? "text-bulb" : score < opponentScore ? "text-muted" : "text-text";
  return (
    <div className="flex items-center gap-3">
      <TeamMark team={team} size={size} />
      <span className="min-w-0 flex-1 truncate text-team">{team.name}</span>
      <span className={`font-mono text-score ${tone}`}>{score}</span>
    </div>
  );
}
