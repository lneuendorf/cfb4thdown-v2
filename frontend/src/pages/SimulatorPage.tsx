import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DecisionCard } from "../components/DecisionCard";
import { DecisionChip } from "../components/DecisionChip";
import { Notice, PageHeader } from "../components/PageHeader";
import { SegmentedControl } from "../components/SegmentedControl";
import { useApi } from "../hooks/useApi";
import { confidenceLabel, formatPeriod, formatRate, formatWp, optionLabel } from "../lib/format";
import type { Option, SimulateResult } from "../lib/types";

// Opens on a situation with a clear answer (sitemap §5: never an empty form).
export const SIM_DEFAULTS = {
  distance: 2,
  ytg: 40,
  off: 17,
  def: 21,
  q: 4,
  clock: "6:00",
  oto: 3,
  dto: 3,
  spread: 0,
  home: "neutral",
} as const;

type Key = keyof typeof SIM_DEFAULTS;
const DEBOUNCE_MS = 250;

function isClock(text: string): boolean {
  const match = /^(\d{1,2}):(\d{2})$/.exec(text);
  if (!match) return false;
  const seconds = Number(match[1]) * 60 + Number(match[2]);
  return Number(match[2]) < 60 && seconds <= 900;
}

function spot(ytg: number): string {
  if (ytg === 50) return "Midfield";
  return ytg > 50 ? `Own ${100 - ytg}` : `Opponent ${ytg}`;
}

function spreadLabel(spread: number): string {
  if (spread === 0) return "Evenly matched";
  const pts = Math.abs(spread).toFixed(Math.abs(spread) % 1 ? 1 : 0);
  return spread < 0 ? `Favored by ${pts}` : `Underdog by ${pts}`;
}

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n));
}

/** Decision simulator (sitemap §5). Every input is in the URL, so any situation is shareable. */
export function SimulatorPage() {
  const [params, setParams] = useSearchParams();
  const read = <K extends Key>(key: K): (typeof SIM_DEFAULTS)[K] => {
    const raw = params.get(key);
    const fallback = SIM_DEFAULTS[key];
    if (raw === null) return fallback;
    return (typeof fallback === "number" ? Number(raw) : raw) as (typeof SIM_DEFAULTS)[K];
  };
  const s = {
    distance: clamp(read("distance"), 1, 99),
    ytg: clamp(read("ytg"), 1, 99),
    off: clamp(read("off"), 0, 150),
    def: clamp(read("def"), 0, 150),
    q: clamp(read("q"), 1, 4),
    clock: isClock(read("clock")) ? read("clock") : SIM_DEFAULTS.clock,
    oto: clamp(read("oto"), 0, 3),
    dto: clamp(read("dto"), 0, 3),
    spread: clamp(read("spread"), -30, 30),
    home: (["home", "away", "neutral"].includes(read("home")) ? read("home") : "neutral") as
      | "home"
      | "away"
      | "neutral",
  };
  const distance = Math.min(s.distance, s.ytg);

  const set = (next: Partial<Record<Key, string | number>>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (String(v) === String(SIM_DEFAULTS[k as Key])) p.delete(k);
      else p.set(k, String(v));
    }
    setParams(p, { replace: true });
  };

  const query = new URLSearchParams({
    distance: String(distance),
    yards_to_goal: String(s.ytg),
    offense_score: String(s.off),
    defense_score: String(s.def),
    period: String(s.q),
    clock: s.clock,
    offense_timeouts: String(s.oto),
    defense_timeouts: String(s.dto),
    spread: String(s.spread),
    home: s.home,
  }).toString();

  // Debounce so dragging a slider doesn't fire a request per pixel.
  const [path, setPath] = useState(`/simulate?${query}`);
  useEffect(() => {
    const t = setTimeout(() => setPath(`/simulate?${query}`), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query]);
  const { state, data, error } = useApi<SimulateResult>(path, null, { keepPrevious: true });
  const [copied, setCopied] = useState(false);

  // The clock box keeps what's typed; only a valid M:SS reaches the URL and the model.
  const [clockText, setClockText] = useState<string>(s.clock);
  useEffect(() => setClockText(s.clock), [s.clock]);
  const clockValid = isClock(clockText);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Simulator" title="Decision simulator">
        Set up any fourth down and see what the model recommends.{" "}
        <Link to="/methodology#grading" className="text-text underline decoration-line underline-offset-4">
          How it decides
        </Link>
      </PageHeader>

      <div className="grid gap-6 md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <section aria-label="Situation" className="space-y-5 rounded-card border border-line bg-panel p-4">
          <Field label="Distance" value={distance === s.ytg ? "Goal" : `${distance} yd`}>
            <Stepper value={distance} min={1} max={s.ytg} onChange={(v) => set({ distance: v })} label="Distance" />
          </Field>

          <Field label="Line of scrimmage" value={spot(s.ytg)}>
            <input
              type="range"
              aria-label="Line of scrimmage, yards from your own goal line"
              min={1}
              max={99}
              value={100 - s.ytg}
              onChange={(e) => set({ ytg: 100 - Number(e.target.value) })}
              className="h-10 w-full accent-text"
            />
            <div className="flex justify-between font-mono text-label text-muted">
              <span>OWN GOAL</span>
              <span>50</span>
              <span>OPP GOAL</span>
            </div>
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Your score">
              <Stepper value={s.off} min={0} max={150} onChange={(v) => set({ off: v })} label="Your score" />
            </Field>
            <Field label="Opponent">
              <Stepper value={s.def} min={0} max={150} onChange={(v) => set({ def: v })} label="Opponent score" />
            </Field>
          </div>

          <div className="flex flex-wrap items-end gap-4">
            <Field label="Quarter">
              <SegmentedControl
                label="Quarter"
                value={String(s.q)}
                options={["1", "2", "3", "4"].map((q) => ({ value: q, label: `Q${q}` }))}
                onChange={(v) => set({ q: v })}
              />
            </Field>
            <Field label="Clock">
              <input
                aria-label="Clock remaining in the quarter"
                inputMode="numeric"
                value={clockText}
                onChange={(e) => {
                  setClockText(e.target.value);
                  if (isClock(e.target.value)) set({ clock: e.target.value });
                }}
                className="min-h-[40px] w-[88px] rounded-control border border-line bg-field px-2 text-center font-mono text-delta"
              />
            </Field>
          </div>

          <Field label="Matchup" value={spreadLabel(s.spread)}>
            <input
              type="range"
              aria-label="Point spread for your team; left is favored"
              min={-28}
              max={28}
              step={0.5}
              value={s.spread}
              onChange={(e) => set({ spread: Number(e.target.value) })}
              className="h-10 w-full accent-text"
            />
            <div className="flex justify-between text-label text-muted">
              <span>Favored</span>
              <span>Underdog</span>
            </div>
          </Field>

          <details className="group">
            <summary className="flex min-h-[40px] cursor-pointer items-center text-meta text-muted hover:text-text">
              Site and timeouts
            </summary>
            <div className="mt-3 space-y-4">
              <Field label="Site">
                <SegmentedControl
                  label="Site"
                  value={s.home}
                  options={[
                    { value: "home", label: "Home" },
                    { value: "away", label: "Away" },
                    { value: "neutral", label: "Neutral" },
                  ]}
                  onChange={(v) => set({ home: v })}
                />
              </Field>
              <div className="flex flex-wrap gap-4">
                <Field label="Your timeouts">
                  <SegmentedControl
                    label="Your timeouts"
                    value={String(s.oto)}
                    options={["0", "1", "2", "3"].map((n) => ({ value: n, label: n }))}
                    onChange={(v) => set({ oto: v })}
                  />
                </Field>
                <Field label="Their timeouts">
                  <SegmentedControl
                    label="Their timeouts"
                    value={String(s.dto)}
                    options={["0", "1", "2", "3"].map((n) => ({ value: n, label: n }))}
                    onChange={(v) => set({ dto: v })}
                  />
                </Field>
              </div>
            </div>
          </details>

          <button
            type="button"
            onClick={() => setParams(new URLSearchParams(), { replace: true })}
            className="min-h-[40px] text-meta text-muted underline decoration-line underline-offset-4 hover:text-text"
          >
            Reset
          </button>
        </section>

        <section aria-label="Model output" aria-live="polite" className="space-y-4">
          <p className="font-mono text-meta text-muted">
            4th &amp; {distance === s.ytg ? "goal" : distance} · {spot(s.ytg)} · {formatPeriod(s.q)} {s.clock} ·{" "}
            {s.off}–{s.def}
          </p>
          {!clockValid ? (
            <Notice>Enter the clock as minutes and seconds, from 0:00 to 15:00.</Notice>
          ) : state === "error" && !data ? (
            <Notice>{error?.message ?? "The simulator couldn't run."}</Notice>
          ) : (
            <Result data={data} />
          )}
          <button
            type="button"
            onClick={() => {
              void navigator.clipboard?.writeText(window.location.href).then(() => setCopied(true));
              setTimeout(() => setCopied(false), 2000);
            }}
            className="min-h-[40px] rounded-control border border-line px-3 text-meta text-muted hover:text-text"
          >
            {copied ? "Link copied" : "Copy link to this situation"}
          </button>
        </section>
      </div>

      {data && <History data={data} />}
      <MobileSummary data={data} />
      {/* Room for the pinned summary on phones. */}
      <div aria-hidden className="h-12 md:hidden" />
    </div>
  );
}

const OPTIONS: { option: Option; key: "wp_go" | "wp_field_goal" | "wp_punt" }[] = [
  { option: "go", key: "wp_go" },
  { option: "field_goal", key: "wp_field_goal" },
  { option: "punt", key: "wp_punt" },
];

function Result({ data }: { data: SimulateResult | undefined }) {
  return (
    <div className="space-y-4 rounded-card border border-line bg-panel p-4">
      <div className="min-h-[64px]">
        <p className="font-mono text-label uppercase tracking-wide text-muted">Model recommends</p>
        {data ? (
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <span className="text-section font-medium">{optionLabel(data.recommendation)}</span>
            <DecisionChip kind="recommendation" option={data.recommendation} />
            <span className="text-meta text-muted">
              {confidenceLabel(data.confidence)}
              {data.margin != null && (
                <>
                  {" "}
                  by <span className="font-mono">{formatWp(data.margin)}</span> WP
                </>
              )}
            </span>
          </div>
        ) : (
          <p className="mt-1 text-section text-muted">—</p>
        )}
      </div>

      <ul className="space-y-3">
        {OPTIONS.map(({ option, key }) => {
          const wp = data?.[key] ?? null;
          const best = data?.recommendation === option;
          return (
            <li key={option}>
              <div className="flex items-baseline justify-between gap-2">
                <span className={`text-body ${best ? "text-text" : "text-muted"}`}>{optionLabel(option)}</span>
                <span className={`font-mono text-delta ${best ? "text-text" : "text-muted"}`}>
                  {!data ? "—" : wp == null ? <span className="font-sans text-meta">not an option</span> : formatWp(wp)}
                </span>
              </div>
              <div className="mt-1 h-[5px] rounded-[3px] bg-inset">
                {wp != null && (
                  <div className={`h-full rounded-[3px] ${best ? "bg-text" : "bg-muted"}`} style={{ width: `${Math.round(wp * 100)}%` }} />
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <dl className="grid grid-cols-3 gap-px overflow-hidden rounded-card border border-line bg-line">
        <Detail label="Converts" value={formatRate(data?.p_convert)} />
        <Detail label="FG good" value={data?.p_fg_make == null ? "—" : formatRate(data.p_fg_make)} />
        <Detail
          label="Punt: they start"
          value={data?.punt_opponent_yards_to_goal == null ? "—" : String(Math.round(100 - data.punt_opponent_yards_to_goal))}
          prefix={data?.punt_opponent_yards_to_goal == null ? undefined : "Own"}
        />
      </dl>
      <p className="text-meta text-muted">
        Win probability for your team after each choice. Assumes typical weather and the matchup above; the model
        doesn&rsquo;t know injuries, play calls or momentum.
      </p>
    </div>
  );
}

function History({ data }: { data: SimulateResult }) {
  const h = data.historical;
  const c = h.criteria;
  const band = (lo: number, hi: number, fmt: (n: number) => string) =>
    lo === hi ? fmt(lo) : `${fmt(lo)} to ${fmt(hi)}`;
  // "down 4 to 8", "up 1 to 3", "tied", "down 9 or more".
  const scoreBand = (lo: number, hi: number) => {
    if (lo === 0 && hi === 0) return "tied";
    const [side, a, b] = hi < 0 ? ["down", -hi, -lo] : ["up", lo, hi];
    return b >= 99 ? `${side} ${a} or more` : a === b ? `${side} ${a}` : `${side} ${a} to ${b}`;
  };
  return (
    <section aria-labelledby="history-title" className="space-y-3">
      <h2 id="history-title" className="font-mono text-label uppercase tracking-wide text-muted">
        Real situations like this
      </h2>
      <p className="text-meta text-muted">
        4th &amp; {band(c.distance[0], Math.min(c.distance[1], 99), String)}
        {c.distance[1] >= 99 ? "+" : ""}, {c.yards_to_goal[0]}–{c.yards_to_goal[1]} yards from the goal,{" "}
        {scoreBand(c.score_diff[0], c.score_diff[1])}, {formatPeriod(c.period)}. FBS
        offenses since 2013.
      </p>
      {h.similar_situations === 0 ? (
        <Notice>No graded fourth down since 2013 matches this closely.</Notice>
      ) : (
        <>
          <p className="max-w-prose text-body">
            This has come up <span className="font-mono">{h.similar_situations}</span>{" "}
            {h.similar_situations === 1 ? "time" : "times"}. Coaches went for it{" "}
            <span className="font-mono">{formatRate(h.went_for_it)}</span> of the time, kicked a field goal{" "}
            <span className="font-mono">{formatRate(h.kicked_field_goal)}</span> and punted{" "}
            <span className="font-mono">{formatRate(h.punted)}</span>. The model said go{" "}
            <span className="font-mono">{formatRate(h.model_said_go)}</span> of the time.
          </p>
          <div className="space-y-3">
            {h.examples.map((d) => (
              <DecisionCard key={d.id} decision={d} href={`/game/${d.game_id}#play-${d.id}`} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Field({ label, value, children }: { label: string; value?: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-label uppercase tracking-wide text-muted">{label}</span>
        {value && <span className="text-meta text-text">{value}</span>}
      </div>
      {children}
    </div>
  );
}

function Stepper({ value, min, max, onChange, label }: { value: number; min: number; max: number; onChange: (v: number) => void; label: string }) {
  const button = "min-h-[40px] min-w-[40px] rounded-control border border-line text-delta text-muted hover:text-text disabled:opacity-40";
  return (
    <div className="flex items-center gap-2">
      <button type="button" aria-label={`Decrease ${label}`} disabled={value <= min} onClick={() => onChange(value - 1)} className={button}>
        −
      </button>
      <span aria-live="polite" className="min-w-[2.5ch] text-center font-mono text-stat">
        {value}
      </span>
      <button type="button" aria-label={`Increase ${label}`} disabled={value >= max} onClick={() => onChange(value + 1)} className={button}>
        +
      </button>
    </div>
  );
}

function Detail({ label, value, prefix }: { label: string; value: string; prefix?: string }) {
  return (
    <div className="bg-panel px-3 py-2">
      <dt className="font-mono text-label uppercase tracking-label text-muted">{label}</dt>
      <dd className="text-delta">
        {prefix && <span className="text-body">{prefix} </span>}
        <span className="font-mono">{value}</span>
      </dd>
    </div>
  );
}

/** Phones: the result sits below the inputs, so keep the answer pinned to the bottom edge. */
function MobileSummary({ data }: { data: SimulateResult | undefined }) {
  if (!data) return null;
  return (
    <div className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-deep px-4 py-2 md:hidden">
      <div className="flex items-center gap-2">
        <DecisionChip kind="recommendation" option={data.recommendation} />
        <span className="text-meta text-text">{optionLabel(data.recommendation)}</span>
        <span className="ml-auto font-mono text-meta text-muted">
          {OPTIONS.map(({ option, key }) =>
            data[key] == null ? null : (
              <span key={option} className={`ml-2 ${data.recommendation === option ? "text-text" : ""}`}>
                {option === "field_goal" ? "FG" : option === "go" ? "Go" : "Punt"} {formatWp(data[key])}
              </span>
            ),
          )}
        </span>
      </div>
    </div>
  );
}
