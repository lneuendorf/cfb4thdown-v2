interface Option<T extends string> {
  value: T;
  label: string;
}

/** A row of toggle buttons for one choice (subject, metric). Active option in text color, not amber. */
export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex gap-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`min-h-[40px] rounded-control border px-3 text-meta ${value === o.value ? "border-text text-text" : "border-line text-muted hover:text-text"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export const SELECT_CLASS =
  "min-h-[40px] max-w-full rounded-control border border-line bg-panel px-2 text-meta text-text";
