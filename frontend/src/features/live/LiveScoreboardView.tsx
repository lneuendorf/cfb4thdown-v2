import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  DecisionCard,
  DecisionCardSkeleton,
  PendingDecisionCard,
  PendingSlotEmpty,
} from "../../components/DecisionCard";
import { LightBank, liveBankTotal } from "../../components/LightBank";
import { Notice, PageHeader } from "../../components/PageHeader";
import { StatStrip, type Stat } from "../../components/StatStrip";
import { formatDelta, formatRate } from "../../lib/format";
import type { LiveScoreboard, WeekScoreboard } from "../../lib/types";

export type LoadState = "loading" | "error" | "ready";
type Filter = "all" | "mistakes";

type LiveScoreboardViewProps = {
  state: LoadState;
  stale?: boolean;
  generatedAt?: string;
} & (
  | { mode?: "live"; data?: LiveScoreboard }
  /** Latest graded week (Phase 2 home page, and the out-of-season fallback). */
  | { mode: "week"; data?: WeekScoreboard }
);

const FEED_PAGE = 20;

export function seasonTypeLabel(week: number, seasonType: string): string {
  return seasonType === "postseason" ? "Postseason" : `Week ${week}`;
}

/**
 * Home page (sitemap §1), rendered from `GET /scoreboard/live` (live mode, Phase 6) or
 * `GET /scoreboard/latest` (week mode). Conference and top-25 filters wait for Phase 3.
 */
export function LiveScoreboardView(props: LiveScoreboardViewProps) {
  const { state, stale = false, generatedAt } = props;
  const week = props.mode === "week" ? props.data : undefined;
  const data: LiveScoreboard | undefined = props.data;
  const isWeek = props.mode === "week";
  const [filter, setFilter] = useState<Filter>("all");
  const [shown, setShown] = useState(FEED_PAGE);
  const decisions = useMemo(
    () => (data?.decisions ?? []).filter((d) => filter === "all" || d.verdict === "mistake"),
    [data, filter],
  );
  const live = data?.games_live ?? 0;
  const period = isWeek ? "this week" : "today";

  const stats: Stat[] = isWeek
    ? [
        {
          label: "Games graded",
          value: week ? `${week.games_graded}/${week.games_total}` : "—",
        },
        { label: "Fourth downs", value: String(week?.fourth_downs_today ?? 0) },
        {
          label: "WP lost per game",
          value: formatDelta(-(week?.wp_lost_per_game ?? 0)),
          tone: (week?.wp_lost_per_game ?? 0) > 0 ? "bad" : "default",
        },
        { label: "Followed model", value: formatRate(week?.followed_model_rate) },
      ]
    : [
        { label: "Games live", value: String(live) },
        { label: "Fourth downs today", value: String(data?.fourth_downs_today ?? 0) },
        {
          label: "WP lost",
          value: formatDelta(-(data?.wp_lost_today ?? 0)),
          tone: (data?.wp_lost_today ?? 0) > 0 ? "bad" : "default",
        },
        { label: "Followed model", value: formatRate(data?.followed_model_rate) },
      ];

  return (
    <div>
      <PageHeader
        eyebrow={
          isWeek
            ? week
              ? `${seasonTypeLabel(week.week, week.season_type)} · ${week.season}${week.is_complete ? "" : " · in progress"}`
              : "Latest week"
            : live > 0
              ? `${live} games live`
              : "Scoreboard"
        }
        title="Fourth downs"
        bank={
          isWeek ? undefined : (
            // Reserve the bank's row while loading so nothing shifts when data arrives.
            <div className="min-h-[9px]">
              {data && <LightBank lit={live} total={liveBankTotal(live)} label={`${live} games live`} />}
            </div>
          )
        }
      >
        {isWeek
          ? "Every graded fourth down from the latest week, ranked by how much win probability was at stake."
          : "Every fourth down today, graded against a win-probability model and ranked by how much it mattered."}
      </PageHeader>

      {stale && (
        <p className="mb-3 font-mono text-meta text-muted">
          Updates are delayed{generatedAt ? ` · as of ${new Date(generatedAt).toLocaleTimeString()}` : ""}
        </p>
      )}

      {state === "error" && !data ? (
        <Notice>The scoreboard couldn&rsquo;t load. Try again in a minute.</Notice>
      ) : (
        <div className="space-y-6">
          <StatStrip loading={!data} stats={stats} />

          {!isWeek && (
            <section aria-label="Pending fourth down">
              {!data ? (
                <PendingSlotEmpty message="Loading…" />
              ) : data.pending ? (
                <PendingDecisionCard pending={data.pending} />
              ) : (
                <PendingSlotEmpty
                  message={
                    live > 0
                      ? "No game is sitting on fourth down right now. The next one appears here before the snap."
                      : "No games are live."
                  }
                />
              )}
            </section>
          )}

          <section aria-labelledby="feed-title" className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="feed-title" className="font-mono text-label uppercase tracking-wide text-muted">
                {isWeek ? "This week" : "Today"}, by WP impact
              </h2>
              <div role="group" aria-label="Filter decisions" className="flex gap-1">
                {(["all", "mistakes"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    aria-pressed={filter === f}
                    onClick={() => {
                      setFilter(f);
                      setShown(FEED_PAGE);
                    }}
                    className={`min-h-[40px] rounded-control border px-3 text-meta ${filter === f ? "border-text text-text" : "border-line text-muted"}`}
                  >
                    {f === "all" ? "All" : "Mistakes only"}
                  </button>
                ))}
              </div>
            </div>

            {!data ? (
              <div className="space-y-3">
                <DecisionCardSkeleton />
                <DecisionCardSkeleton />
                <DecisionCardSkeleton />
              </div>
            ) : decisions.length === 0 ? (
              filter === "mistakes" && data.decisions.length > 0 ? (
                <Notice>No fourth down {period} was graded a mistake by the model.</Notice>
              ) : (
                <Notice>
                  No fourth downs graded {period} yet.{" "}
                  <Link to="/games" className="text-text underline decoration-line underline-offset-4">
                    Browse games
                  </Link>
                  .
                </Notice>
              )
            ) : (
              <>
                <div className="space-y-3">
                  {decisions.slice(0, shown).map((d, i) => (
                    <DecisionCard
                      key={d.id}
                      decision={d}
                      highlighted={i === 0}
                      href={`/game/${d.game_id}#play-${d.id}`}
                    />
                  ))}
                </div>
                {decisions.length > shown && (
                  <button
                    type="button"
                    onClick={() => setShown((n) => n + FEED_PAGE)}
                    className="min-h-[40px] w-full rounded-card border border-line text-meta text-muted hover:text-text"
                  >
                    Show more ({decisions.length - shown} left)
                  </button>
                )}
                {week && week.decisions_total > week.decisions.length && decisions.length <= shown && (
                  <p className="text-meta text-muted">
                    Showing the {week.decisions.length} highest-impact of {week.decisions_total} fourth downs.{" "}
                    <Link to="/games" className="text-text underline decoration-line underline-offset-4">
                      Every game
                    </Link>{" "}
                    has its full list.
                  </p>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
