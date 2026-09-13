import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { DecisionCard, DecisionCardSkeleton } from "../components/DecisionCard";
import { Notice, PageHeader } from "../components/PageHeader";
import { RankedRow } from "../components/RankedRow";
import { ReviewNotice } from "../components/ReviewNotice";
import { StatStrip } from "../components/StatStrip";
import { TeamMark } from "../components/TeamMark";
import { seasonTypeLabel } from "../features/live/LiveScoreboardView";
import { useApi } from "../hooks/useApi";
import { formatDelta, formatRate } from "../lib/format";
import type { WeekInReview, WeekScoreboard } from "../lib/types";

const NAV_BUTTON =
  "min-h-[40px] rounded-control border border-line px-3 text-meta text-muted hover:text-text disabled:opacity-40";

/** Week in Review (sitemap §3). /week shows the latest complete week. */
export function WeekInReviewPage() {
  const { season, week } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const seasonType = params.get("season_type") ?? "regular";
  const path =
    season && week ? `/week-in-review/${season}/${week}?season_type=${seasonType}` : "/week-in-review/latest";
  const { state, data, error } = useApi<WeekInReview>(path);
  const [showAll, setShowAll] = useState(false);

  const go = (delta: number) => {
    if (!data) return;
    setShowAll(false);
    navigate(`/week/${data.season}/${data.week + delta}${data.season_type === "postseason" ? "?season_type=postseason" : ""}`);
  };

  if (error?.status === 404) {
    return (
      <div>
        <PageHeader eyebrow="Week in review" title="No games that week" />
        <Link to="/week" className="inline-flex min-h-[40px] items-center underline decoration-line underline-offset-4">
          Latest week
        </Link>
      </div>
    );
  }

  const topConference = data?.by_conference[0]?.wp_lost_per_game ?? 0;

  return (
    <div className="space-y-8">
      {/* The top section is built to stand alone in a screenshot. */}
      <section className="space-y-4">
        <PageHeader
          eyebrow={data ? `${seasonTypeLabel(data.week, data.season_type)} · ${data.season}` : "Week in review"}
          title="Week in review"
        />
        {data && !data.is_complete && (
          <Notice>Some games this week aren&rsquo;t final yet. Totals will change as they&rsquo;re graded.</Notice>
        )}
        <div>
          {/* Headline is per game: a league-wide sum of WP percentages (hundreds of %) doesn't read
              as a number. The total stays in the API as wp_lost_total. */}
          <p className="font-mono text-label uppercase tracking-wide text-muted">WP surrendered per game, league-wide</p>
          <p className={`font-mono text-score ${data && (data.wp_lost_per_game ?? 0) > 0 ? "text-bad" : "text-text"}`}>
            {data ? formatDelta(-(data.wp_lost_per_game ?? 0)) : "—"}
          </p>
        </div>
        <StatStrip
          loading={!data}
          stats={[
            { label: "Games graded", value: data ? `${data.games_graded}/${data.games_total}` : "—" },
            { label: "Fourth downs", value: String(data?.fourth_downs_total ?? 0) },
            { label: "Mistakes", value: String(data?.mistakes ?? 0) },
            { label: "Followed model", value: formatRate(data?.followed_model_rate) },
          ]}
        />
      </section>

      <div className="flex items-center gap-2">
        <button type="button" disabled={!data || data.week <= 1} onClick={() => go(-1)} className={NAV_BUTTON}>
          Previous week
        </button>
        <button type="button" disabled={!data} onClick={() => go(1)} className={NAV_BUTTON}>
          Next week
        </button>
      </div>

      {state === "error" ? (
        <Notice>{error?.message ?? "This week couldn't load."}</Notice>
      ) : (
        <>
          {data?.commentary && (
            <section aria-label="Commentary" className="max-w-prose space-y-3 text-body">
              {data.commentary.split(/\n\s*\n/).map((para, i) => (
                <p key={i}>{para}</p>
              ))}
            </section>
          )}

          <section aria-labelledby="worst-title" className="space-y-3">
            <h2 id="worst-title" className="font-mono text-label uppercase tracking-wide text-muted">
              Worst call
            </h2>
            {!data ? (
              <DecisionCardSkeleton />
            ) : data.worst_call ? (
              <DecisionCard decision={data.worst_call} href={`/game/${data.worst_call.game_id}#play-${data.worst_call.id}`} />
            ) : (
              <Notice>Every graded call this week matched the model.</Notice>
            )}
          </section>

          <section aria-labelledby="best-title" className="space-y-3">
            <h2 id="best-title" className="font-mono text-label uppercase tracking-wide text-muted">
              Best call
            </h2>
            <p className="text-meta text-muted">The coach followed the model where its edge over the next option was largest.</p>
            {!data ? (
              <DecisionCardSkeleton />
            ) : data.best_call ? (
              <DecisionCard decision={data.best_call} href={`/game/${data.best_call.game_id}#play-${data.best_call.id}`} />
            ) : (
              <Notice>No graded call this week matched the model.</Notice>
            )}
          </section>

          <section aria-labelledby="conf-title" className="space-y-2">
            <h2 id="conf-title" className="font-mono text-label uppercase tracking-wide text-muted">
              WP lost per game, by conference
            </h2>
            {data ? (
              <ol className="divide-y divide-line">
                {data.by_conference.map((c, i) => (
                  <li key={c.conference}>
                    <RankedRow
                      rank={i + 1}
                      name={c.conference}
                      detail={`${c.games} games`}
                      value={formatDelta(-c.wp_lost_per_game)}
                      fraction={topConference > 0 ? c.wp_lost_per_game / topConference : 0}
                      tone="bad"
                    />
                  </li>
                ))}
              </ol>
            ) : (
              <div aria-hidden className="h-[260px] rounded-card bg-panel" />
            )}
          </section>

          <section aria-labelledby="movers-title" className="space-y-2">
            <h2 id="movers-title" className="font-mono text-label uppercase tracking-wide text-muted">
              Biggest movers on the Punt Index
            </h2>
            {data && data.punt_index_movers.length === 0 ? (
              <Notice>
                Movers appear once coaches have three graded games this season.{" "}
                <Link to="/punt-index" className="text-text underline decoration-line underline-offset-4">
                  See the Punt Index
                </Link>
              </Notice>
            ) : (
              <ul className="divide-y divide-line">
                {data?.punt_index_movers.map((m) => (
                  <li key={m.coach_id}>
                    <Link to={`/punt-index/coach/${m.coach_id}`} className="flex min-h-[52px] items-center gap-3 py-2 hover:bg-panel">
                      <TeamMark team={m.team} size={30} />
                      <span className="min-w-0 flex-1 truncate text-team">{m.coach_name}</span>
                      <span className="font-mono text-meta text-muted">
                        {m.rank_before} → <span className="text-text">{m.rank_now}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {data && <AllDecisions week={data} open={showAll} onOpen={() => setShowAll(true)} />}
          <ReviewNotice />
        </>
      )}
    </div>
  );
}

function AllDecisions({ week, open, onOpen }: { week: WeekInReview; open: boolean; onOpen: () => void }) {
  const path = open
    ? `/scoreboard/week/${week.season}/${week.week}?season_type=${week.season_type}&limit=500`
    : null;
  const { data } = useApi<WeekScoreboard>(path);
  if (!open) {
    return (
      <button type="button" onClick={onOpen} className="min-h-[40px] w-full rounded-card border border-line text-meta text-muted hover:text-text">
        Show all {week.fourth_downs_total} FBS fourth downs
      </button>
    );
  }
  return (
    <section aria-labelledby="all-title" className="space-y-3">
      <h2 id="all-title" className="font-mono text-label uppercase tracking-wide text-muted">
        Every fourth down, by WP impact
      </h2>
      {!data ? (
        <DecisionCardSkeleton />
      ) : (
        data.decisions.map((d) => <DecisionCard key={d.id} decision={d} href={`/game/${d.game_id}#play-${d.id}`} />)
      )}
    </section>
  );
}
