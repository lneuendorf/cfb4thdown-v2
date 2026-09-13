import { formatDelta, formatPeriod } from "../lib/format";
import type { TickerGame } from "../lib/types";

function describe(g: TickerGame): string {
  const parts = [
    `${g.away ?? "—"} ${g.away_score}`,
    `${g.home ?? "—"} ${g.home_score}`,
  ];
  if (g.status === "live")
    parts.push(`${formatPeriod(g.period)} ${g.clock ?? ""}`.trim());
  else if (g.status === "final") parts.push("Final");
  if (g.wp_delta_last != null) parts.push(`${formatDelta(g.wp_delta_last)} WP`);
  return parts.join(" · ");
}

/**
 * Scores with the last fourth-down WP delta. Scrolls only while games are live (the one
 * animation the design spec allows); static and horizontally scrollable otherwise.
 */
export function Ticker({
  games,
  live,
}: {
  games: TickerGame[];
  live: boolean;
}) {
  if (games.length === 0)
    return <div aria-hidden className="h-8 border-b border-bulb bg-deep" />;
  const text = games.map(describe).join("  |  ");
  const content = (
    <span className="whitespace-pre px-4 font-mono text-meta tracking-ticker text-bulb">
      {text}
    </span>
  );
  return (
    <div
      className="h-8 overflow-x-auto border-b border-bulb bg-deep"
      aria-label="Scores"
    >
      {live ? (
        // Content duplicated so the loop is seamless; the copy is hidden from screen readers.
        <div
          className="animate-ticker flex h-full w-max items-center"
          style={{
            ["--ticker-duration" as string]: `${Math.max(30, games.length * 6)}s`,
          }}
        >
          {content}
          <span
            aria-hidden
            className="whitespace-pre px-4 font-mono text-meta tracking-ticker text-bulb"
          >
            {"|  "}
            {text}
          </span>
        </div>
      ) : (
        <div className="flex h-full w-max items-center">{content}</div>
      )}
    </div>
  );
}
