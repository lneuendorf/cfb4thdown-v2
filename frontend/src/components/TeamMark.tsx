import { useState } from "react";
import type { Team } from "../lib/types";

type Size = 30 | 34 | 44;

const SIZE_CLASS: Record<Size, string> = {
  30: "h-[30px] w-[30px]",
  34: "h-[34px] w-[34px]",
  44: "h-[44px] w-[44px]",
};

const PAD_CLASS: Record<Size, string> = { 30: "p-[3px]", 34: "p-[4px]", 44: "p-[5px]" };

/**
 * Fixed square on --bg-inset. Logos have inconsistent aspect ratios and some are mostly white,
 * so the backing and fixed box are non-negotiable. Falls back to the abbreviation in mono.
 */
export function TeamMark({ team, size = 30 }: { team: Team; size?: Size }) {
  const [failed, setFailed] = useState(false);
  const abbreviation = (team.abbreviation ?? team.name).slice(0, 4).toUpperCase();
  const showLogo = team.logo_url && !failed;
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center overflow-hidden rounded-control bg-inset ${SIZE_CLASS[size]} ${showLogo ? PAD_CLASS[size] : ""}`}
    >
      {showLogo ? (
        <img
          src={team.logo_url ?? undefined}
          alt={team.name}
          loading="lazy"
          className="h-full w-full object-contain"
          onError={() => setFailed(true)}
        />
      ) : (
        <span
          aria-label={team.name}
          className={`font-mono text-muted ${size === 44 ? "text-meta" : "text-label"}`}
        >
          {abbreviation}
        </span>
      )}
    </span>
  );
}
