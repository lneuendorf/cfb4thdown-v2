import { Link, useSearchParams } from "react-router-dom";
import { Notice, PageHeader } from "../components/PageHeader";
import { RankedRow } from "../components/RankedRow";
import { ReviewNotice } from "../components/ReviewNotice";
import { SELECT_CLASS, SegmentedControl } from "../components/SegmentedControl";
import { useApi } from "../hooks/useApi";
import { formatDelta, formatRate } from "../lib/format";
import type { PuntIndex, PuntMetric, PuntSubject } from "../lib/types";

const FIRST_SEASON = 2013;

/** The Punt Index (sitemap §4). All filter state lives in the URL so a ranking can be shared. */
export function PuntIndexPage() {
  const [params, setParams] = useSearchParams();
  const subject = (params.get("subject") as PuntSubject) || "coach";
  const metric = (params.get("metric") as PuntMetric) || "wp_lost";
  const from = params.get("from");
  const to = params.get("to");
  const conference = params.get("conference") ?? "";
  const returning = params.get("returning") === "1";

  const query = new URLSearchParams({ subject, metric });
  if (from) query.set("season_from", from);
  if (to) query.set("season_to", to);
  if (conference) query.set("conference", conference);
  if (returning && subject === "coach") query.set("returning", "true");
  const { state, data, error } = useApi<PuntIndex>(`/punt-index?${query}`);

  const set = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null || v === "") p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: true });
  };

  const lastSeason = Math.max(data?.season_to ?? FIRST_SEASON, new Date().getFullYear());
  const seasons = Array.from({ length: lastSeason - FIRST_SEASON + 1 }, (_, i) => lastSeason - i);
  const ranked = data?.rows.filter((r) => r.rank !== null) ?? [];
  const top = ranked[0]?.value ?? 0;
  const seasonLabel = data
    ? data.season_from === data.season_to
      ? String(data.season_to)
      : `${data.season_from}–${data.season_to}`
    : "";

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={seasonLabel ? `The Punt Index · ${seasonLabel}` : "The Punt Index"} title="The Punt Index">
        {subject === "coach" ? "Coaches" : "Teams"} ranked by win probability given up by kicking or punting when
        the model said go.{" "}
        <Link to="/methodology#punt-index" className="text-text underline decoration-line underline-offset-4">
          How it&rsquo;s measured
        </Link>
      </PageHeader>

      <ReviewNotice />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <SegmentedControl
          label="Rank"
          value={subject}
          options={[
            { value: "coach", label: "Coaches" },
            { value: "team", label: "Teams" },
          ]}
          onChange={(v) => set({ subject: v === "coach" ? null : v })}
        />
        <SegmentedControl
          label="Metric"
          value={metric}
          options={[
            { value: "wp_lost", label: "WP lost" },
            { value: "go_rate", label: "Go rate" },
          ]}
          onChange={(v) => set({ metric: v === "wp_lost" ? null : v })}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-meta text-muted">
          From
          <select
            className={SELECT_CLASS}
            value={from ?? String(data?.season_from ?? "")}
            onChange={(e) => set({ from: e.target.value })}
          >
            {seasons.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-meta text-muted">
          To
          <select
            className={SELECT_CLASS}
            value={to ?? String(data?.season_to ?? "")}
            onChange={(e) => set({ to: e.target.value })}
          >
            {seasons.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <select
          aria-label="Conference"
          className={SELECT_CLASS}
          value={conference}
          onChange={(e) => set({ conference: e.target.value })}
        >
          <option value="">All FBS</option>
          {data?.conferences.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        {subject === "coach" && (
          <label className="flex min-h-[40px] items-center gap-2 text-meta text-muted">
            <input
              type="checkbox"
              checked={returning}
              onChange={(e) => set({ returning: e.target.checked ? "1" : null })}
            />
            Current coaches only
          </label>
        )}
      </div>

      <p className="text-meta text-muted">
        {metric === "wp_lost"
          ? "WP lost per game on fourth downs where the model said go and the team kicked or punted. Highest first."
          : "Share of the model's go recommendations the team went for. Lowest first."}{" "}
        Greyed rows have fewer than {data?.min_games ?? 6} graded games and aren&rsquo;t ranked.
      </p>

      {state === "error" ? (
        <Notice>{error?.message ?? "The Punt Index couldn't load."}</Notice>
      ) : !data ? (
        <div aria-hidden className="space-y-2">
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} className="h-[52px] rounded-card bg-panel" />
          ))}
        </div>
      ) : data.rows.length === 0 ? (
        <Notice>No graded fourth downs match these filters.</Notice>
      ) : (
        <ol className="divide-y divide-line">
          {data.rows.map((r) => (
            <li key={r.id}>
              <Link to={`/punt-index/${subject}/${r.id}`} className="block hover:bg-panel">
                <RankedRow
                  rank={r.rank}
                  team={r.team}
                  name={r.name}
                  detail={`${subject === "coach" ? `${r.team.abbreviation ?? r.team.name} · ` : ""}${r.games} games`}
                  value={metric === "wp_lost" ? formatDelta(-r.value) : formatRate(r.value)}
                  fraction={metric === "wp_lost" ? (top > 0 ? r.value / top : 0) : r.value}
                  tone={metric === "wp_lost" ? "bad" : "good"}
                  sampleWarning={r.sample_warning}
                />
              </Link>
            </li>
          ))}
        </ol>
      )}

      {data && subject === "coach" && data.unattributed_fourth_downs > 0 && (
        <p className="text-meta text-muted">
          <span className="font-mono">{data.unattributed_fourth_downs}</span> fourth downs from seasons with a coaching
          change that can&rsquo;t be split reliably aren&rsquo;t credited to any coach. They still count in the team
          ranking.
        </p>
      )}
    </div>
  );
}
