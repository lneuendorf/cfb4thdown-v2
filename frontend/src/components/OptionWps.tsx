import { formatWp, optionShort } from "../lib/format";
import type { Option, OptionWps as Wps } from "../lib/types";

const ORDER: { option: Option; key: keyof Wps }[] = [
  { option: "go", key: "wp_go" },
  { option: "field_goal", key: "wp_field_goal" },
  { option: "punt", key: "wp_punt" },
];

/**
 * Win probability for each option. An infeasible option (FG beyond the model's range, punt
 * inside the 30) is null in the API and reads "not an option", never a number.
 */
export function OptionWps({ wps, recommendation }: { wps: Wps; recommendation: Option }) {
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-meta text-muted">
      {ORDER.map(({ option, key }) => {
        const value = wps[key];
        return (
          <div key={option} className="flex gap-1">
            <dt>{optionShort(option)}</dt>
            <dd className={option === recommendation ? "text-text" : undefined}>
              {value == null ? <span className="font-sans">not an option</span> : formatWp(value)}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
