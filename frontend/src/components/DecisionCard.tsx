import {
  confidenceLabel,
  formatDelta,
  formatPeriod,
  situation,
  teamLabel,
  verdictLabel,
} from "../lib/format";
import { Link } from "react-router-dom";
import type { Decision, PendingDecision, Verdict } from "../lib/types";
import { DecisionChipPair } from "./DecisionChip";
import { OptionWps } from "./OptionWps";
import { TeamMark } from "./TeamMark";

const BORDER: Record<Verdict, string> = {
  correct: "border-good",
  marginal: "border-mid",
  mistake: "border-bad",
};

const DELTA_TONE: Record<Verdict, string> = {
  correct: "text-good",
  marginal: "text-mid",
  mistake: "text-bad",
};

// Pending card and its empty slot share a footprint so polls never shift the page.
const PENDING_HEIGHT = "min-h-[176px]";

// Left accent: never round the border side.
const SHELL = "rounded-r-card rounded-l-none border-l-[3px] bg-panel px-4 py-3";

/**
 * A completed fourth down. Anchored at #play-{id} so a single call can be linked. `href` links
 * the situation line (to the game page from feeds).
 */
export function DecisionCard({
  decision: d,
  highlighted = false,
  href,
}: {
  decision: Decision;
  highlighted?: boolean;
  href?: string;
}) {
  const estimated = [
    d.clock_source === "interpolated" ? "clock" : null,
    d.timeouts_imputed || d.timeouts_uncertain ? "timeouts" : null,
  ].filter(Boolean);
  const title = situation(d.down, d.distance, d.yards_to_goal, d.offense, d.defense);
  return (
    <article
      id={`play-${d.id}`}
      className={`${SHELL} ${BORDER[d.verdict]} ${highlighted ? "outline outline-1 outline-line" : ""}`}
    >
      <div className="flex items-start gap-3">
        <TeamMark team={d.offense} size={30} />
        <div className="min-w-0 flex-1">
          <p className="text-card">
            {href ? (
              <Link to={href} className="hover:underline hover:decoration-line hover:underline-offset-4">
                {title}
              </Link>
            ) : (
              title
            )}
          </p>
          <p className="font-mono text-meta text-muted">
            {formatPeriod(d.period)} {d.clock} · {teamLabel(d.offense)} {d.offense_score} ·{" "}
            {teamLabel(d.defense)} {d.defense_score}
            {d.is_live && " · live"}
          </p>
          {estimated.length > 0 && (
            <p className="text-meta text-muted" title="Reconstructed from incomplete play-by-play">
              Estimated {estimated.join(" and ")}
            </p>
          )}
        </div>
        <div className="text-right">
          <p className={`font-mono text-delta ${DELTA_TONE[d.verdict]}`}>{formatDelta(d.wp_delta)}</p>
          <p className="text-label uppercase tracking-label text-muted">WP</p>
        </div>
      </div>
      <div className="mt-2 border-t border-dashed border-line-dashed pt-2">
        <OptionWps wps={d} recommendation={d.recommendation} />
        {d.play_text && <p className="mt-1 line-clamp-2 text-meta text-muted">{d.play_text}</p>}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <DecisionChipPair recommendation={d.recommendation} decision={d.decision} verdict={d.verdict} />
        <span className="text-meta text-muted">
          {verdictLabel(d.verdict)}
          {d.confidence && ` · ${confidenceLabel(d.confidence)}`}
        </span>
      </div>
    </article>
  );
}

/**
 * The recommendation before the snap. The card slot is always rendered (PendingSlotEmpty) so a
 * pending decision appearing or clearing between polls never shifts the page.
 */
export function PendingDecisionCard({ pending: p }: { pending: PendingDecision }) {
  const offenseScore = p.offense_is_home ? p.home_score : p.away_score;
  const defenseScore = p.offense_is_home ? p.away_score : p.home_score;
  return (
    <article className={`${SHELL} ${PENDING_HEIGHT} border-bulb`} aria-live="polite">
      <p className="font-mono text-label uppercase tracking-wide text-bulb">On fourth down now</p>
      <div className="mt-2 flex items-start gap-3">
        <TeamMark team={p.offense} size={30} />
        <div className="min-w-0 flex-1">
          <p className="text-card">{situation(p.down, p.distance, p.yards_to_goal, p.offense, p.defense)}</p>
          <p className="font-mono text-meta text-muted">
            {formatPeriod(p.period)} {p.clock} · {teamLabel(p.offense)} {offenseScore} ·{" "}
            {teamLabel(p.defense)} {defenseScore}
          </p>
        </div>
      </div>
      <div className="mt-2 border-t border-dashed border-line-dashed pt-2">
        <OptionWps wps={p} recommendation={p.recommendation} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-meta text-muted">Model says</span>
        <DecisionChipPair recommendation={p.recommendation} />
        {p.confidence && <span className="text-meta text-muted">{confidenceLabel(p.confidence)}</span>}
      </div>
      {(p.polled_at || p.timeouts_uncertain) && (
        <p className="mt-1 text-meta text-muted">
          {p.polled_at && (
            <>
              As of <span className="font-mono">{new Date(p.polled_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}</span>
            </>
          )}
          {p.polled_at && p.timeouts_uncertain && " · "}
          {p.timeouts_uncertain && "Timeouts may be off this late in the half"}
        </p>
      )}
    </article>
  );
}

/** Same footprint as a pending card, for when no game is on fourth down. */
export function PendingSlotEmpty({ message }: { message: string }) {
  return (
    <div className={`${SHELL} ${PENDING_HEIGHT} flex items-center border-line`}>
      <p className="text-body text-muted">{message}</p>
    </div>
  );
}

export function DecisionCardSkeleton() {
  return <div aria-hidden className={`${SHELL} h-[150px] border-line`} />;
}
