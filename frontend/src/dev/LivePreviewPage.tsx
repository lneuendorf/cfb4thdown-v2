import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Ticker } from "../components/Ticker";
import { LiveScoreboardView, type LoadState } from "../features/live/LiveScoreboardView";
import type { Envelope, LiveScoreboard } from "../lib/types";
import { FAKE_SCOREBOARD } from "./fakeFixtures";

// Real ESPN captures replayed through the live grading code by
// `uv run python -m analysis.live_fixtures export` (backend). Loaded lazily, dev only.
const payloads = import.meta.glob<Envelope<LiveScoreboard>>("./fixtures/live/*/**/*.json", {
  import: "default",
});
const indexes = import.meta.glob<FixtureIndex>("./fixtures/live/*/index.json", {
  import: "default",
  eager: true,
});

interface FixtureIndex {
  session: string;
  busiest_live_games: number;
  scenes: { name: string; description: string; polled_at: string }[];
  sequence: string[];
}

type Override = "none" | "loading" | "error" | "stale" | "empty";

const AUTOPLAY_MS = 2500;

export function LivePreviewPage() {
  const [params, setParams] = useSearchParams();
  const sessions = useMemo(
    () => Object.values(indexes).sort((a, b) => b.session.localeCompare(a.session)),
    [],
  );
  const session = sessions.find((s) => s.session === params.get("session")) ?? sessions[0];
  const scene = params.get("scene") ?? session?.scenes[0]?.name ?? "fake";
  const frame = Number(params.get("frame") ?? 0);
  const override = (params.get("state") as Override | null) ?? "none";
  const [playing, setPlaying] = useState(false);
  const [envelope, setEnvelope] = useState<Envelope<LiveScoreboard> | null>(null);

  const set = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: true });
  };

  useEffect(() => {
    if (scene === "fake" || !session) {
      setEnvelope({ data: FAKE_SCOREBOARD, meta: { generated_at: "2099-01-01T00:00:00Z", stale: false, source: "fake" } });
      return;
    }
    const file =
      scene === "sequence"
        ? `./fixtures/live/${session.session}/sequence/${String(frame).padStart(2, "0")}.json`
        : `./fixtures/live/${session.session}/${scene}.json`;
    const load = payloads[file];
    if (!load) {
      setEnvelope(null);
      return;
    }
    let cancelled = false;
    load().then((e) => !cancelled && setEnvelope(e));
    return () => {
      cancelled = true;
    };
  }, [session, scene, frame]);

  const frames = session?.sequence.length ?? 0;
  useEffect(() => {
    if (!playing || scene !== "sequence" || frames === 0) return;
    const t = setTimeout(() => set({ frame: String((frame + 1) % frames) }), AUTOPLAY_MS);
    return () => clearTimeout(t);
  });

  let data = envelope?.data;
  let state: LoadState = data ? "ready" : "loading";
  if (override === "loading") {
    data = undefined;
    state = "loading";
  } else if (override === "error") {
    data = undefined;
    state = "error";
  } else if (override === "empty" && data) {
    data = { ...data, games_live: 0, fourth_downs_today: 0, wp_lost_today: 0, followed_model_rate: null, pending: null, decisions: [] };
  }

  const control = "min-h-[40px] max-w-full rounded-control border border-line bg-panel px-2 text-meta text-text";

  return (
    <div className="-mx-4">
      <Ticker games={data?.ticker ?? []} live={(data?.games_live ?? 0) > 0} />
      <div className="space-y-2 border-b border-line bg-panel px-4 py-3">
        <p className="font-mono text-label uppercase tracking-wide text-muted">
          Dev preview · {scene === "fake" ? "fake fixture" : "real ESPN capture, graded by the model"}
          {envelope && ` · polled ${envelope.meta.generated_at}`}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {sessions.length > 1 && (
            <select aria-label="Session" className={control} value={session?.session} onChange={(e) => set({ session: e.target.value, scene: null, frame: null })}>
              {sessions.map((s) => (
                <option key={s.session}>{s.session}</option>
              ))}
            </select>
          )}
          <select aria-label="Scene" className={control} value={scene} onChange={(e) => set({ scene: e.target.value, frame: null })}>
            {session?.scenes.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}: {s.description}
              </option>
            ))}
            {session && <option value="sequence">sequence: {frames} consecutive polls</option>}
            <option value="fake">fake: component fixture values</option>
          </select>
          <select aria-label="Force state" className={control} value={override} onChange={(e) => set({ state: e.target.value === "none" ? null : e.target.value })}>
            <option value="none">as captured</option>
            <option value="loading">loading</option>
            <option value="error">error</option>
            <option value="stale">stale</option>
            <option value="empty">no games / no decisions</option>
          </select>
          {scene === "sequence" && (
            <>
              <button type="button" className={control} onClick={() => set({ frame: String((frame - 1 + frames) % frames) })}>
                Prev
              </button>
              <span className="font-mono text-meta text-muted">
                {frame + 1}/{frames}
              </span>
              <button type="button" className={control} onClick={() => set({ frame: String((frame + 1) % frames) })}>
                Next
              </button>
              <button type="button" className={control} aria-pressed={playing} onClick={() => setPlaying((p) => !p)}>
                {playing ? "Pause" : "Play"}
              </button>
            </>
          )}
        </div>
      </div>
      <div className="px-4">
        <LiveScoreboardView state={state} data={data} stale={override === "stale"} generatedAt={envelope?.meta.generated_at} />
      </div>
    </div>
  );
}
