import type { Team } from "../lib/types";
import { TeamMark } from "./TeamMark";

interface RankedRowProps {
  /** null for unranked rows (below the minimum sample). */
  rank: number | null;
  /** Omitted for rows that aren't a team, e.g. a conference. */
  team?: Team;
  name: string;
  value: string;
  /** Bar fill, 0–1, relative to the top row. */
  fraction: number;
  tone: "good" | "bad";
  /** Below the minimum sample: shown greyed out, never dropped (api-contract: Punt Index). */
  sampleWarning?: boolean;
  detail?: string;
}

export function RankedRow({
  rank,
  team,
  name,
  value,
  fraction,
  tone,
  sampleWarning = false,
  detail,
}: RankedRowProps) {
  const width = `${Math.round(Math.min(Math.max(fraction, 0), 1) * 100)}%`;
  return (
    <div
      className={`flex min-h-[40px] items-center gap-3 py-2 ${sampleWarning ? "opacity-50" : ""}`}
    >
      <span
        className={`w-7 text-right font-mono text-delta ${rank !== null && rank <= 3 ? "text-bulb" : "text-muted"}`}
      >
        {rank ?? "—"}
      </span>
      {team && <TeamMark team={team} size={30} />}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-team">{name}</span>
          {detail && (
            <span className="truncate text-label text-muted">
              {detail}
            </span>
          )}
        </div>
        <div className="mt-1 h-[5px] rounded-[3px] bg-inset">
          <div
            className={`h-full rounded-[3px] ${tone === "good" ? "bg-good" : "bg-bad"}`}
            style={{ width }}
          />
        </div>
      </div>
      <span className="font-mono text-delta">{value}</span>
    </div>
  );
}
