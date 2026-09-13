import { Link, useParams } from "react-router-dom";
import { Notice, PageHeader } from "../components/PageHeader";
import { ReviewNotice } from "../components/ReviewNotice";
import { StatStrip } from "../components/StatStrip";
import { TeamMark } from "../components/TeamMark";
import { useApi } from "../hooks/useApi";
import { formatDelta, formatRate } from "../lib/format";
import type { PuntIndexDetail } from "../lib/types";

/** One coach or team, season by season (sitemap §4: coach detail with a season-over-season trend). */
export function PuntIndexDetailPage() {
  const { subject = "coach", id = "" } = useParams();
  const valid = (subject === "coach" || subject === "team") && /^\d+$/.test(id);
  const { state, data, error } = useApi<PuntIndexDetail>(valid ? `/punt-index/${subject}/${id}` : null);

  if (!valid || error?.status === 404) {
    return (
      <div>
        <PageHeader eyebrow="The Punt Index" title="Not found">
          No graded fourth downs for that {subject === "team" ? "team" : "coach"}.
        </PageHeader>
        <Link to="/punt-index" className="inline-flex min-h-[40px] items-center underline decoration-line underline-offset-4">
          Back to the Punt Index
        </Link>
      </div>
    );
  }

  const totals = data?.seasons.reduce(
    (acc, s) => ({
      games: acc.games + s.games,
      lost: acc.lost + s.wp_lost_total,
      recs: acc.recs + s.go_recommendations,
      went: acc.went + s.went_for_it,
    }),
    { games: 0, lost: 0, recs: 0, went: 0 },
  );
  const maxLost = Math.max(0.0001, ...(data?.seasons.map((s) => s.wp_lost) ?? [0]));

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={subject === "coach" ? "The Punt Index · Coach" : "The Punt Index · Team"} title={data?.name ?? "Loading"}>
        Season by season. <Link to="/punt-index" className="text-text underline decoration-line underline-offset-4">All rankings</Link>
      </PageHeader>

      <ReviewNotice />

      {state === "error" ? (
        <Notice>{error?.message ?? "This page couldn't load."}</Notice>
      ) : (
        <>
          <StatStrip
            loading={!data}
            stats={[
              { label: "Seasons", value: String(data?.seasons.length ?? 0) },
              { label: "Games", value: String(totals?.games ?? 0) },
              {
                label: "WP lost per game",
                value: formatDelta(totals && totals.games ? -totals.lost / totals.games : 0),
                tone: totals && totals.lost > 0 ? "bad" : "default",
              },
              { label: "Go rate when told go", value: formatRate(totals && totals.recs ? totals.went / totals.recs : null) },
            ]}
          />

          <div className="max-w-full overflow-x-auto rounded-card border border-line">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="bg-panel">
                  {["Season", "Team", "Games", "Told go", "Went", "Go rate", "WP lost / game", "Rank"].map((h, i) => (
                    <th
                      key={h}
                      scope="col"
                      className={`whitespace-nowrap px-3 py-2 font-mono text-label font-normal uppercase tracking-label text-muted ${i === 0 ? "sticky left-0 bg-panel" : ""}`}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!data
                  ? Array.from({ length: 4 }, (_, i) => (
                      <tr key={i} className="h-[45px] border-t border-line" aria-hidden>
                        <td colSpan={8} />
                      </tr>
                    ))
                  : data.seasons.map((s) => (
                      <tr key={s.season} className="border-t border-line">
                        <th scope="row" className="sticky left-0 whitespace-nowrap bg-field px-3 py-2 font-mono text-meta font-normal">
                          {s.season}
                          {data.interim_seasons.includes(s.season) && <span className="ml-1 font-sans text-muted">(mid-season)</span>}
                        </th>
                        <td className="whitespace-nowrap px-3 py-2">
                          <span className="inline-flex items-center gap-2 text-body">
                            <TeamMark team={s.team} size={30} />
                            {s.team.abbreviation ?? s.team.name}
                          </span>
                        </td>
                        <td className="px-3 py-2 font-mono text-meta">{s.games}</td>
                        <td className="px-3 py-2 font-mono text-meta">{s.go_recommendations}</td>
                        <td className="px-3 py-2 font-mono text-meta">{s.went_for_it}</td>
                        <td className="px-3 py-2 font-mono text-meta">{formatRate(s.go_rate)}</td>
                        <td className="min-w-[140px] px-3 py-2">
                          <span className="font-mono text-meta">{formatDelta(-s.wp_lost)}</span>
                          <div className="mt-1 h-[5px] rounded-[3px] bg-inset">
                            <div className="h-full rounded-[3px] bg-bad" style={{ width: `${Math.round((s.wp_lost / maxLost) * 100)}%` }} />
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-meta text-muted">
                          {s.rank ? `${s.rank} of ${s.ranked_of}` : "—"}
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
          <p className="text-meta text-muted">
            Rank is by WP lost per game among FBS {subject === "coach" ? "coaches" : "teams"} with at least 6 graded games
            that season. &ldquo;Mid-season&rdquo; marks a season this coach took over partway through.
          </p>
        </>
      )}
    </div>
  );
}
