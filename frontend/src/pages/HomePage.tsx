import { LiveScoreboardView } from "../features/live/LiveScoreboardView";
import { useApi } from "../hooks/useApi";
import type { LiveScoreboard, WeekScoreboard } from "../lib/types";

// Sitemap §1: poll every 20-30 s while any game is live, and stop entirely when none are.
const LIVE_POLL_MS = 20_000;
// Between slates, check now and then whether a slate has started (the ticker loop on the server
// notices kickoffs within a minute).
const IDLE_CHECK_MS = 5 * 60 * 1000;

/** Live scoreboard during a slate; the latest graded week otherwise. */
export function HomePage() {
  const live = useApi<LiveScoreboard>(
    "/scoreboard/live",
    (d) => (d && d.games_live > 0 ? LIVE_POLL_MS : IDLE_CHECK_MS),
    { keepPrevious: true },
  );
  const isLive = (live.data?.games_live ?? 0) > 0;
  const week = useApi<WeekScoreboard>(
    live.state === "loading" || isLive ? null : "/scoreboard/latest?limit=200",
  );

  if (isLive || live.state === "loading") {
    return (
      <LiveScoreboardView
        mode="live"
        state={live.state}
        data={live.data}
        stale={live.meta?.stale}
        generatedAt={live.meta?.generated_at}
      />
    );
  }
  return (
    <LiveScoreboardView
      mode="week"
      state={week.state}
      data={week.data}
      stale={week.meta?.stale}
      generatedAt={week.meta?.generated_at}
    />
  );
}
