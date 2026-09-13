import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatPeriod, formatWp, teamLabel } from "../lib/format";
import type { Decision, Team, Verdict, WpPoint } from "../lib/types";

// Recharts draws SVG, which accepts CSS variables, so colors still come from tokens.
const VERDICT_STROKE: Record<Verdict, string> = {
  correct: "var(--good)",
  marginal: "var(--mid)",
  mistake: "var(--bad)",
};

export const CHART_HEIGHT = 240;
const GAME_SECONDS = 3600;

interface ChartPoint {
  elapsed: number;
  wp: number;
  label: string;
}

/**
 * Home-team win probability before every snap, with fourth downs marked as rings in their
 * verdict color (sitemap §2). Regulation only: overtime isn't modeled.
 */
export function WpChart({ series, decisions, home }: { series: WpPoint[]; decisions: Decision[]; home: Team }) {
  const points = useMemo<ChartPoint[]>(
    () =>
      series.map((p) => ({
        elapsed: GAME_SECONDS - p.seconds_remaining,
        wp: p.home_wp,
        label: `${formatPeriod(p.period)} ${p.clock}`,
      })),
    [series],
  );
  const markers = useMemo(() => {
    const byPlay = new Map(series.filter((p) => p.play_id).map((p) => [p.play_id, p]));
    return decisions.flatMap((d) => {
      const p = byPlay.get(d.id);
      return p ? [{ d, x: GAME_SECONDS - p.seconds_remaining, y: p.home_wp }] : [];
    });
  }, [series, decisions]);

  return (
    <figure aria-label={`${home.name} win probability chart`} className="rounded-card border border-line bg-panel p-3">
      <figcaption className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-label uppercase tracking-wide text-muted">
          {teamLabel(home)} win probability
        </span>
        <span className="flex gap-3 text-meta text-muted">
          <Legend stroke="var(--good)" label="Matched" />
          <Legend stroke="var(--mid)" label="Marginal" />
          <Legend stroke="var(--bad)" label="Mistake" />
        </span>
      </figcaption>
      <div style={{ height: CHART_HEIGHT }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis
              dataKey="elapsed"
              type="number"
              domain={[0, GAME_SECONDS]}
              ticks={[0, 900, 1800, 2700, 3600]}
              tickFormatter={(v: number) => (v >= GAME_SECONDS ? "END" : `Q${v / 900 + 1}`)}
              stroke="var(--line)"
              tick={{ fill: "var(--text-muted)", fontSize: 11, fontFamily: "JetBrains Mono" }}
            />
            <YAxis
              domain={[0, 1]}
              ticks={[0, 0.5, 1]}
              tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
              stroke="var(--line)"
              tick={{ fill: "var(--text-muted)", fontSize: 11, fontFamily: "JetBrains Mono" }}
            />
            <ReferenceLine y={0.5} stroke="var(--line-dashed)" strokeDasharray="4 4" />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: "var(--line-dashed)" }}
              content={({ active, payload }) => {
                const point = payload?.[0]?.payload as ChartPoint | undefined;
                if (!active || !point) return null;
                return (
                  <div className="rounded-control border border-line bg-deep px-2 py-1 font-mono text-meta">
                    <span className="text-muted">{point.label}</span> {formatWp(point.wp)}
                  </div>
                );
              }}
            />
            <Line
              type="linear"
              dataKey="wp"
              stroke="var(--text)"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            {markers.map(({ d, x, y }) => (
              <ReferenceDot
                key={d.id}
                x={x}
                y={y}
                r={5}
                fill="var(--bg-panel)"
                stroke={VERDICT_STROKE[d.verdict]}
                strokeWidth={2}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

function Legend({ stroke, label }: { stroke: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <svg width="10" height="10" aria-hidden>
        <circle cx="5" cy="5" r="3.5" fill="none" stroke={stroke} strokeWidth="2" />
      </svg>
      {label}
    </span>
  );
}

export function WpChartSkeleton() {
  return <div aria-hidden className="rounded-card border border-line bg-panel" style={{ height: CHART_HEIGHT + 50 }} />;
}
