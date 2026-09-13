interface LightBankProps {
  /** Fully lit bulbs. */
  lit: number;
  /** Total bulbs shown. Bulbs past `lit + half` are off. */
  total: number;
  /** Half-lit bulbs after the lit ones. */
  half?: number;
  /** What the bank encodes, for screen readers, e.g. "15 games live". Required: it is never decorative. */
  label: string;
}

/**
 * A readout, not decoration (design-spec: Light bank). No animation. Rows of 12 bulbs, so the
 * bank is identical at 390px and desktop (a row of 12 is 185px wide).
 */
export function LightBank({ lit, total, half = 0, label }: LightBankProps) {
  const bulbs = Array.from({ length: Math.max(total, 0) }, (_, i) =>
    i < lit ? "bg-bulb" : i < lit + half ? "bg-bulb-dim" : "bg-bulb-dark",
  );
  return (
    <div role="img" aria-label={label} className="grid w-max grid-cols-[repeat(12,9px)] gap-[7px]">
      {bulbs.map((cls, i) => (
        <span key={i} className={`block h-[9px] w-[9px] rounded-full ${cls}`} />
      ))}
    </div>
  );
}

/**
 * Bulbs for a count of live games: one lit per live game, padded with off bulbs to the next
 * multiple of 12 so rows stay full. A second row appears only once more than 12 games are live.
 */
export function liveBankTotal(live: number): number {
  return Math.max(12, Math.ceil(live / 12) * 12);
}
