import type { ReactNode } from "react";
import { DecisionChip, DecisionChipPair } from "../components/DecisionChip";
import {
  DecisionCard,
  DecisionCardSkeleton,
  PendingDecisionCard,
  PendingSlotEmpty,
} from "../components/DecisionCard";
import { LightBank } from "../components/LightBank";
import { PageHeader } from "../components/PageHeader";
import { RankedRow } from "../components/RankedRow";
import { ScoreRow } from "../components/ScoreRow";
import { StatStrip } from "../components/StatStrip";
import { TeamMark } from "../components/TeamMark";
import { Ticker } from "../components/Ticker";
import { FAKE_AWAY, FAKE_DECISIONS, FAKE_HOME, FAKE_LONG, FAKE_PENDING, FAKE_TICKER } from "./fakeFixtures";

function Specimen({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 border-t border-line pt-6">
      <h2 className="font-mono text-label uppercase tracking-wide text-muted">{title}</h2>
      {children}
    </section>
  );
}

/** Dev-only gallery of the shared components, rendered from obviously fake fixtures. */
export function ComponentsPage() {
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Dev" title="Components">
        Every shared component in each of its states. Values are fake.
      </PageHeader>

      <Specimen title="Ticker (static, live)">
        <Ticker games={FAKE_TICKER} live={false} />
        <Ticker games={FAKE_TICKER} live />
        <Ticker games={[]} live={false} />
      </Specimen>

      <Specimen title="Light bank">
        <LightBank lit={8} total={12} label="8 of 12" />
        <LightBank lit={3} half={4} total={12} label="3 lit, 4 half" />
        <LightBank lit={0} total={12} label="none lit" />
      </Specimen>

      <Specimen title="Team mark (no logo fallback, broken logo, sizes)">
        <div className="flex items-end gap-3">
          <TeamMark team={FAKE_HOME} size={30} />
          <TeamMark team={FAKE_AWAY} size={34} />
          <TeamMark team={FAKE_LONG} size={44} />
          <TeamMark team={{ ...FAKE_HOME, logo_url: "/does-not-exist.png" }} size={44} />
        </div>
      </Specimen>

      <Specimen title="Score rows (leading, trailing, tied)">
        <div className="max-w-sm space-y-2 rounded-card bg-panel p-4">
          <ScoreRow team={FAKE_HOME} score={22} opponentScore={11} />
          <ScoreRow team={FAKE_AWAY} score={11} opponentScore={22} />
        </div>
        <div className="max-w-sm space-y-2 rounded-card bg-panel p-4">
          <ScoreRow team={FAKE_LONG} score={11} opponentScore={11} size={34} />
          <ScoreRow team={FAKE_AWAY} score={11} opponentScore={11} size={34} />
        </div>
      </Specimen>

      <Specimen title="Decision chips">
        <div className="flex flex-wrap gap-3">
          <DecisionChip kind="recommendation" option="go" />
          <DecisionChip kind="recommendation" option="field_goal" />
          <DecisionChip kind="recommendation" option="punt" />
          <DecisionChipPair recommendation="go" decision="go" verdict="correct" />
          <DecisionChipPair recommendation="go" decision="punt" verdict="mistake" />
          <DecisionChipPair recommendation="field_goal" decision="go" verdict="marginal" />
        </div>
      </Specimen>

      <Specimen title="Stat strip (ready, loading)">
        <StatStrip
          stats={[
            { label: "Games live", value: "11" },
            { label: "Fourth downs", value: "111" },
            { label: "WP lost", value: "−11.1%", tone: "bad" },
            { label: "Followed model", value: "11%" },
          ]}
        />
        <StatStrip loading stats={[{ label: "Games live", value: "" }, { label: "WP lost", value: "" }, { label: "Followed", value: "" }]} />
      </Specimen>

      <Specimen title="Pending card and its empty slot (same height)">
        <PendingDecisionCard pending={FAKE_PENDING} />
        <PendingSlotEmpty message="No game is sitting on fourth down right now." />
      </Specimen>

      <Specimen title="Decision cards (correct, mistake, marginal with infeasible punt, only option, skeleton)">
        <div className="space-y-3">
          {FAKE_DECISIONS.map((d, i) => (
            <DecisionCard key={d.id} decision={d} highlighted={i === 1} />
          ))}
          <DecisionCardSkeleton />
        </div>
      </Specimen>

      <Specimen title="Ranked rows (top 3 amber, sample warning)">
        <div className="max-w-xl">
          <RankedRow rank={1} team={FAKE_HOME} name="Coach Fixture" value="−11.1%" fraction={1} tone="bad" detail="11 games" />
          <RankedRow rank={2} team={FAKE_AWAY} name="Coach Mock" value="−5.5%" fraction={0.5} tone="bad" />
          <RankedRow rank={4} team={FAKE_LONG} name="Coach Placeholder" value="−2.2%" fraction={0.2} tone="bad" sampleWarning detail="2 games" />
        </div>
      </Specimen>
    </div>
  );
}
