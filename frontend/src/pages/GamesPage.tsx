import { Link, useSearchParams } from "react-router-dom";
import { Notice, PageHeader } from "../components/PageHeader";
import { TeamMark } from "../components/TeamMark";
import { seasonTypeLabel } from "../features/live/LiveScoreboardView";
import { useApi } from "../hooks/useApi";
import { formatDelta, teamLabel } from "../lib/format";
import type { GameSummary, GamesList, GradingStatus } from "../lib/types";

const GRADING_LABEL: Record<GradingStatus, string> = {
  graded: "Graded",
  no_fourth_downs: "Graded",
  failed_quality_gate: "Not graded",
  awaiting_plays: "Awaiting play-by-play",
  not_final: "Not final",
  not_processed: "Not graded yet",
  provisional: "Live grades",
};

/** Games for one week, linking to game pages. Defaults to the latest graded week. */
export function GamesPage() {
  const [params, setParams] = useSearchParams();
  const season = params.get("season");
  const week = params.get("week");
  const seasonType = params.get("season_type") ?? "regular";
  const path =
    season && week ? `/games?season=${season}&week=${week}&season_type=${seasonType}` : "/games";
  const { state, data, error } = useApi<GamesList>(path);

  const go = (delta: number) => {
    if (!data) return;
    setParams({ season: String(data.season), week: String(data.week + delta), season_type: data.season_type });
  };

  return (
    <div>
      <PageHeader
        eyebrow={data ? `${seasonTypeLabel(data.week, data.season_type)} · ${data.season}` : "Games"}
        title="Games"
      >
        Every game, with its fourth downs graded against the model.
      </PageHeader>

      <div className="mb-4 flex items-center gap-2">
        <button type="button" disabled={!data || data.week <= 1} onClick={() => go(-1)} className={NAV_BUTTON}>
          Previous week
        </button>
        <button type="button" disabled={!data} onClick={() => go(1)} className={NAV_BUTTON}>
          Next week
        </button>
      </div>

      {state === "error" ? (
        <Notice>{error?.message ?? "Games couldn't load."}</Notice>
      ) : !data ? (
        <div aria-hidden className="space-y-px overflow-hidden rounded-card border border-line bg-line">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="h-[72px] bg-field" />
          ))}
        </div>
      ) : data.games.length === 0 ? (
        <Notice>No games in this week.</Notice>
      ) : (
        <ul className="space-y-px overflow-hidden rounded-card border border-line bg-line">
          {data.games.map((g) => (
            <GameRow key={g.id} game={g} />
          ))}
        </ul>
      )}
    </div>
  );
}

const NAV_BUTTON =
  "min-h-[40px] rounded-control border border-line px-3 text-meta text-muted hover:text-text disabled:opacity-40";

function GameRow({ game: g }: { game: GameSummary }) {
  const graded = g.grading_status === "graded" || g.grading_status === "no_fourth_downs";
  // Live-graded games show their status until batch grades land.
  return (
    <li className="bg-field">
      <Link to={`/game/${g.id}`} className="flex min-h-[72px] items-center gap-3 px-4 py-3 hover:bg-panel">
        <div className="min-w-0 flex-1 space-y-1">
          <TeamLine team={g.away} score={g.away_score} other={g.home_score} />
          <TeamLine team={g.home} score={g.home_score} other={g.away_score} />
        </div>
        <div className="w-[136px] shrink-0 text-right">
          {graded ? (
            <>
              <p className={`font-mono text-delta ${formatDelta(-g.wp_lost) === "0.0%" ? "text-text" : "text-bad"}`}>
                {formatDelta(-g.wp_lost)}
              </p>
              <p className="text-label text-muted">
                WP lost · <span className="font-mono">{g.fourth_downs}</span> fourth downs
              </p>
            </>
          ) : (
            <p className="text-meta text-muted">{GRADING_LABEL[g.grading_status]}</p>
          )}
        </div>
      </Link>
    </li>
  );
}

function TeamLine({ team, score, other }: { team: GameSummary["home"]; score: number | null; other: number | null }) {
  const tone =
    score == null || other == null ? "text-muted" : score > other ? "text-bulb" : score < other ? "text-muted" : "text-text";
  return (
    <div className="flex items-center gap-2">
      <TeamMark team={team} size={30} />
      <span className="min-w-0 flex-1 truncate text-team">{team.name}</span>
      <span className={`font-mono text-delta ${tone}`}>{score ?? "—"}</span>
      <span className="sr-only">{teamLabel(team)}</span>
    </div>
  );
}
