export type StatTone = "default" | "good" | "bad" | "muted";

export interface Stat {
  label: string;
  value: string;
  tone?: StatTone;
}

const TONE: Record<StatTone, string> = {
  default: "text-text",
  good: "text-good",
  bad: "text-bad",
  muted: "text-muted",
};

/** 2–4 metrics separated by hairlines: the grid background shows through a 1px gap. */
export function StatStrip({
  stats,
  loading = false,
}: {
  stats: Stat[];
  loading?: boolean;
}) {
  const cols =
    stats.length >= 4
      ? "grid-cols-2 sm:grid-cols-4"
      : stats.length === 3
        ? "grid-cols-3"
        : "grid-cols-2";
  return (
    <dl
      className={`grid gap-px overflow-hidden rounded-card border border-line bg-line ${cols}`}
    >
      {stats.map((s) => (
        <div key={s.label} className="bg-field px-4 py-3">
          <dt className="font-mono text-label uppercase tracking-label text-muted">
            {s.label}
          </dt>
          <dd
            className={`mt-1 font-mono text-stat ${loading ? "text-muted" : TONE[s.tone ?? "default"]}`}
          >
            {loading ? "—" : s.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
