import { optionShort } from "../lib/format";
import type { Option, Verdict } from "../lib/types";

const RECOMMENDATION_TONE: Record<Option, string> = {
  go: "border-good text-good",
  field_goal: "border-bulb text-bulb",
  punt: "border-muted text-muted",
};

const ACTUAL_TONE: Record<Verdict, string> = {
  correct: "border-good text-good",
  mistake: "border-bad text-bad",
  marginal: "border-mid text-mid",
};

type ChipProps =
  | { kind: "recommendation"; option: Option }
  | { kind: "actual"; option: Option; verdict: Verdict };

export function DecisionChip(props: ChipProps) {
  const tone =
    props.kind === "recommendation" ? RECOMMENDATION_TONE[props.option] : ACTUAL_TONE[props.verdict];
  return (
    <span
      className={`inline-flex items-center rounded-control border px-2 py-[2px] font-mono text-label uppercase tracking-label ${tone}`}
      title={props.kind === "recommendation" ? "Model recommendation" : "What the coach did"}
    >
      {optionShort(props.option)}
    </span>
  );
}

/** `RECOMMENDATION → ACTUAL`. Without an actual (a pending decision) only the recommendation shows. */
export function DecisionChipPair({
  recommendation,
  decision,
  verdict,
}: {
  recommendation: Option;
  decision?: Option;
  verdict?: Verdict;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <DecisionChip kind="recommendation" option={recommendation} />
      {decision && verdict && (
        <>
          <span aria-hidden className="font-mono text-meta text-muted">
            →
          </span>
          <DecisionChip kind="actual" option={decision} verdict={verdict} />
        </>
      )}
    </span>
  );
}
