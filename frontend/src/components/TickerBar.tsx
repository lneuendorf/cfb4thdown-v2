import { useApi } from "../hooks/useApi";
import type { TickerFeed } from "../lib/types";
import { Ticker } from "./Ticker";

const LIVE_POLL_MS = 30_000;

/**
 * Site-wide score ticker from our cached ESPN scores (never ESPN directly). Polls while games
 * are live and stops when none are (sitemap §1). Keeps its 32px row while loading.
 */
export function TickerBar() {
  const { data } = useApi<TickerFeed>("/ticker", (feed) => (feed && feed.games_live > 0 ? LIVE_POLL_MS : null));
  const games = data?.games ?? [];
  const live = (data?.games_live ?? 0) > 0;
  // Out of a slate, only today's finals and upcoming kickoffs are worth a ticker.
  return <Ticker games={live ? games.filter((g) => g.status === "live") : games.slice(0, 20)} live={live} />;
}
