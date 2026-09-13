import { LiveScoreboardView } from "../features/live/LiveScoreboardView";
import { useApi } from "../hooks/useApi";
import type { WeekScoreboard } from "../lib/types";

// Until live grading (roadmap Phase 6), the home page is the latest graded week. It refreshes
// every few minutes so games graded during a Saturday appear without a reload.
const REFRESH_MS = 5 * 60 * 1000;

export function HomePage() {
  const { state, data, meta } = useApi<WeekScoreboard>("/scoreboard/latest?limit=200", REFRESH_MS);
  return (
    <LiveScoreboardView
      mode="week"
      state={state}
      data={data}
      stale={meta?.stale}
      generatedAt={meta?.generated_at}
    />
  );
}
