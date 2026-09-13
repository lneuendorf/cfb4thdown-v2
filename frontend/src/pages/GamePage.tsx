import { useEffect, useMemo } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { DecisionCard, DecisionCardSkeleton } from "../components/DecisionCard";
import { Notice, PageHeader } from "../components/PageHeader";
import { ScoreRow } from "../components/ScoreRow";
import { StatStrip } from "../components/StatStrip";
import { WpChart, WpChartSkeleton } from "../components/WpChart";
import { seasonTypeLabel } from "../features/live/LiveScoreboardView";
import { useApi } from "../hooks/useApi";
import { formatDelta, teamLabel } from "../lib/format";
import type { GameDetail } from "../lib/types";

const STATUS_LABEL = { final: "Final", scheduled: "Scheduled", in_progress: "In progress" } as const;

/** Game page (sitemap §2): the thing people link to after a game ends. */
export function GamePage() {
  const { gameId = "" } = useParams();
  const valid = /^\d+$/.test(gameId);
  const { state, data, meta, error } = useApi<GameDetail>(valid ? `/games/${gameId}` : null);
  const location = useLocation();

  // Deep links (#play-<id>) scroll once the decisions have rendered.
  useEffect(() => {
    if (!data || !location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [data, location.hash]);

  const mostImpactful = useMemo(() => {
    if (!data?.decisions.length) return null;
    return data.decisions.reduce((a, b) => (Math.abs(b.wp_delta ?? 0) > Math.abs(a.wp_delta ?? 0) ? b : a)).id;
  }, [data]);

  useEffect(() => {
    if (data) {
      const g = data.game;
      document.title = `${teamLabel(g.away)} ${g.away_score ?? ""} at ${teamLabel(g.home)} ${g.home_score ?? ""} · cfb4thdown`;
    }
    return () => {
      document.title = "cfb4thdown";
    };
  }, [data]);

  if (!valid || error?.status === 404) {
    return (
      <div>
        <PageHeader eyebrow="Game" title="Game not found">
          There&rsquo;s no game with that id.
        </PageHeader>
        <Link to="/games" className="inline-flex min-h-[40px] items-center underline decoration-line underline-offset-4">
          Browse games
        </Link>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div>
        <PageHeader eyebrow="Game" title="Game" />
        <Notice>{error?.message ?? "This game couldn't load."}</Notice>
      </div>
    );
  }

  const g = data?.game;
  const graded = data?.grading.status === "graded" || data?.grading.status === "no_fourth_downs";
  const netTone = (v: number): "bad" | "default" => (v < 0 ? "bad" : "default");

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          g ? `${seasonTypeLabel(g.week, g.season_type)} · ${g.season} · ${STATUS_LABEL[g.status]}` : "Game"
        }
        title={g ? `${teamLabel(g.away)} at ${teamLabel(g.home)}` : "Loading game"}
      />
      {meta?.stale && <p className="font-mono text-meta text-muted">Updates are delayed.</p>}

      <section aria-label="Score" className="max-w-md space-y-2 rounded-card bg-panel p-4">
        {g ? (
          <>
            <ScoreRow team={g.away} score={g.away_score ?? 0} opponentScore={g.home_score ?? 0} size={34} />
            <ScoreRow team={g.home} score={g.home_score ?? 0} opponentScore={g.away_score ?? 0} size={34} />
          </>
        ) : (
          <div aria-hidden className="h-[84px]" />
        )}
      </section>

      {data && data.grading.message && <Notice>{data.grading.message}</Notice>}

      {(!data || graded) && (
        <>
          <StatStrip
            loading={!data}
            stats={
              g && data
                ? [
                    { label: `${teamLabel(g.away)} fourth downs`, value: String(data.totals.away.fourth_downs) },
                    {
                      label: `${teamLabel(g.away)} WP surrendered`,
                      value: formatDelta(data.totals.away.wp_delta),
                      tone: netTone(data.totals.away.wp_delta),
                    },
                    { label: `${teamLabel(g.home)} fourth downs`, value: String(data.totals.home.fourth_downs) },
                    {
                      label: `${teamLabel(g.home)} WP surrendered`,
                      value: formatDelta(data.totals.home.wp_delta),
                      tone: netTone(data.totals.home.wp_delta),
                    },
                  ]
                : [
                    { label: "Away fourth downs", value: "" },
                    { label: "Away WP surrendered", value: "" },
                    { label: "Home fourth downs", value: "" },
                    { label: "Home WP surrendered", value: "" },
                  ]
            }
          />
          {data && g ? (
            data.wp_series.length > 0 ? (
              <WpChart series={data.wp_series} decisions={data.decisions} home={g.home} />
            ) : null
          ) : (
            <WpChartSkeleton />
          )}
        </>
      )}

      <section aria-labelledby="decisions-title" className="space-y-3">
        <h2 id="decisions-title" className="font-mono text-label uppercase tracking-wide text-muted">
          Fourth downs, in order
        </h2>
        {!data ? (
          <div className="space-y-3">
            <DecisionCardSkeleton />
            <DecisionCardSkeleton />
          </div>
        ) : data.decisions.length === 0 ? (
          <Notice>
            {graded
              ? "No fourth downs in this game were in scope for grading (overtime, penalties and garbage time are left out)."
              : "Fourth downs appear here once the game is graded."}{" "}
            <Link to="/methodology#limitations" className="text-text underline decoration-line underline-offset-4">
              What gets graded
            </Link>
          </Notice>
        ) : (
          <div className="space-y-3">
            {data.decisions.map((d) => (
              <DecisionCard key={d.id} decision={d} highlighted={d.id === mostImpactful} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
