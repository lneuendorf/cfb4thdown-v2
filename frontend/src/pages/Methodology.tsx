import type { ReactNode } from "react";
import { DecisionCard } from "../components/DecisionCard";
import { Notice, PageHeader, SectionTitle } from "../components/PageHeader";
import type { Decision } from "../lib/types";

// Every figure on this page comes from docs/models.md and docs/grades.md (models v2.0.0,
// 2024–25 holdout). The worked example uses illustrative numbers, labeled as such, until the
// review gate in docs/roadmap.md passes.

// Numbers render in mono, words in sans (design-spec: Type).
const NUMERIC = /^[\d.,%–−+ ]+$/;

const SOURCE_REPO = "https://github.com/lneuendorf/cfb4thdown-v2";

const SECTIONS = [
  { id: "idea", title: "The idea" },
  { id: "win-probability", title: "Win probability" },
  { id: "components", title: "The four models" },
  { id: "grading", title: "Grading a decision" },
  { id: "example", title: "A worked example" },
  { id: "punt-index", title: "The Punt Index" },
  { id: "limitations", title: "What the model doesn't know" },
  { id: "data", title: "Data and updates" },
  { id: "issues", title: "Known issues" },
];

const EXAMPLE: Decision = {
  id: "example",
  game_id: "example",
  season: 2026,
  week: null,
  offense: { id: "ex-home", name: "Home team", abbreviation: "HOME" },
  defense: { id: "ex-away", name: "Away team", abbreviation: "AWAY" },
  period: 3,
  clock: "8:00",
  down: 4,
  distance: 2,
  yard_line: 45,
  yards_to_goal: 45,
  offense_score: 14,
  defense_score: 14,
  recommendation: "go",
  decision: "punt",
  confidence: "clear",
  margin: 0.06,
  wp_go: 0.56,
  wp_punt: 0.5,
  wp_field_goal: null,
  wp_delta: -0.06,
  verdict: "mistake",
  outcome: null,
  play_text: null,
  is_live: false,
};

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-3 border-t border-line pt-8">
      <SectionTitle id={id}>{title}</SectionTitle>
      <div className="max-w-prose space-y-3 text-body">{children}</div>
    </section>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="max-w-full overflow-x-auto rounded-card border border-line">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="bg-panel">
            {head.map((h, i) => (
              <th
                key={h}
                scope="col"
                className={`whitespace-nowrap px-3 py-2 font-mono text-label font-normal uppercase tracking-label text-muted ${i === 0 ? "sticky left-0 bg-panel" : ""}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row[0])} className="border-t border-line">
              {row.map((cell, i) =>
                i === 0 ? (
                  <th key={i} scope="row" className="sticky left-0 whitespace-nowrap bg-field px-3 py-2 text-body font-normal">
                    {cell}
                  </th>
                ) : (
                  <td
                    key={i}
                    className={`whitespace-nowrap px-3 py-2 ${NUMERIC.test(String(cell)) ? "font-mono text-meta" : "text-body"}`}
                  >
                    {cell}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const Mono = ({ children }: { children: ReactNode }) => <span className="font-mono">{children}</span>;

export function Methodology() {
  return (
    <div className="space-y-8">
      <PageHeader eyebrow="Methodology" title="How the grades work">
        What the model does, how well it does it, and where it&rsquo;s weakest. Written for skeptics.
      </PageHeader>

      <nav aria-label="On this page" className="flex flex-wrap gap-x-4 gap-y-1">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#${s.id}`} className="inline-flex min-h-[40px] items-center text-meta text-muted hover:text-text">
            {s.title}
          </a>
        ))}
      </nav>

      <Section id="idea" title="The idea">
        <p>
          On fourth down a coach has up to three choices: go for it, kick a field goal, or punt. Each
          choice leads to a range of outcomes, and each outcome leaves the offense with some chance
          of winning the game.
        </p>
        <p>
          The model estimates that chance for each choice and recommends the highest. When the coach
          does something else, the gap between the recommendation and the choice is the win
          probability (WP) the call cost, according to the model.
        </p>
        <p>
          The model recommends. It does not know. Every grade on this site is model output, and this
          page is here so you can judge how much weight to give it.
        </p>
      </Section>

      <Section id="win-probability" title="Win probability">
        <p>
          The core is a win-probability model: given the situation before a snap, how often does the
          team with the ball go on to win? It&rsquo;s a gradient-boosted tree model (XGBoost) trained on{" "}
          <Mono>1,692,153</Mono> pre-snap situations from <Mono>10,694</Mono> FBS games, <Mono>2013</Mono>–
          <Mono>2025</Mono>, on every down, not just fourth.
        </p>
        <p>It sees:</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>score, clock, quarter, field position, down and distance, and timeouts;</li>
          <li>the closing point spread and both teams&rsquo; Elo ratings, as a measure of team strength;</li>
          <li>end-of-game indicators, such as whether the leading team can kneel out the clock.</li>
        </ul>
        <p>
          Some inputs are constrained to push in the obvious direction. For example, more points of
          lead never lowers your chance of winning.
        </p>
        <p>
          We tested it on the <Mono>2024</Mono> and <Mono>2025</Mono> seasons, after fitting it on
          earlier seasons only:
        </p>
        <Table
          head={["Situations", "States", "Calibration error"]}
          rows={[
            ["All downs", "261,728", "1.1%"],
            ["Fourth down", "28,081", "1.1%"],
            ["First quarter", "62,176", "2.6%"],
            ["Fourth quarter, within 8 points", "23,392", "2.9%"],
            ["Final 2 minutes", "12,645", "1.8%"],
          ]}
        />
        <p className="text-muted">
          Calibration error is the average gap between predicted and observed win rates. A model that
          says <Mono>30%</Mono> should see that team win about <Mono>30%</Mono> of the time.
        </p>
      </Section>

      <Section id="components" title="The four models">
        <p>
          Win probability tells us what a situation is worth. Three more models tell us which
          situation each choice leads to:
        </p>
        <Table
          head={["Model", "Predicts", "Uses"]}
          rows={[
            ["Win probability", "Chance the offense wins", "Game state, spread, Elo"],
            ["Conversion", "Chance a fourth-down try succeeds", "Distance, field position, score and time, Elo"],
            ["Field goal", "Chance a kick is good", "Distance, kicking team Elo, wind, rain, altitude, indoors"],
            ["Punt", "Where the other team starts", "Punt spot, Elo"],
          ]}
        />
        <p>
          The assumptions that connect them are measured from the data, not picked by hand. After a
          made field goal or a touchdown, the other team&rsquo;s median start is its own{" "}
          <Mono>25</Mono>. A successful conversion gains a median of <Mono>3</Mono> yards past the line
          to gain and uses about <Mono>29</Mono> seconds before the next snap.
        </p>
        <p>
          Punts are graded over the full spread of punt results, not just the average, because a
          shanked punt and a touchback aren&rsquo;t symmetric.
        </p>
      </Section>

      <Section id="grading" title="Grading a decision">
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <strong className="font-medium">Go for it:</strong> chance of converting × WP after
            converting, plus chance of failing × WP with the other team taking over at that spot.
          </li>
          <li>
            <strong className="font-medium">Field goal:</strong> chance of making it × WP after the
            kickoff, plus chance of missing × WP with the other team at the spot of the kick, or at its
            own <Mono>20</Mono>.
          </li>
          <li>
            <strong className="font-medium">Punt:</strong> WP averaged over where the other team is
            likely to start.
          </li>
        </ul>
        <p>
          Some choices aren&rsquo;t offered. A field goal counts only within <Mono>50</Mono> yards of the
          goal line, and a punt only from <Mono>30</Mono> or more yards away. Outside those ranges the
          models have too little data, so the option shows as &ldquo;not an option&rdquo; rather than a
          number.
        </p>
        <Table
          head={["Label", "Meaning"]}
          rows={[
            ["Matched model", "The coach did what the model recommended"],
            ["Marginal miss", "Didn't match, but cost under 5% WP"],
            ["Model disagreed", "Didn't match, and cost 5% WP or more"],
            ["Clear call", "Best option leads the next by 5% WP or more"],
            ["Close call", "Leads by 2–5%"],
            ["Toss-up", "Leads by under 2%"],
          ]}
        />
        <p>
          Most calls are close. In <Mono>2013</Mono>–<Mono>2025</Mono>, <Mono>76%</Mono> of fourth
          downs were toss-ups, and only about <Mono>1%</Mono> cost <Mono>5%</Mono> WP or more.
        </p>
      </Section>

      <Section id="example" title="A worked example">
        <Notice>Illustrative numbers, chosen to show the arithmetic. Not a real play or a real model output.</Notice>
        <p>
          Tied <Mono>14</Mono>–<Mono>14</Mono> in the third quarter, the home team faces fourth and{" "}
          <Mono>2</Mono> at the away <Mono>45</Mono>.
        </p>
        <ol className="list-decimal space-y-1 pl-5">
          <li>
            Say the conversion model gives a <Mono>60%</Mono> chance of converting. WP after converting
            is <Mono>63%</Mono>; WP after failing, with the other team taking over at its own{" "}
            <Mono>45</Mono>, is <Mono>45.5%</Mono>. Going for it is worth{" "}
            <Mono>0.6 × 63% + 0.4 × 45.5% = 56%</Mono>.
          </li>
          <li>
            Averaged over likely punt results, punting is worth <Mono>50%</Mono>.
          </li>
          <li>From <Mono>45</Mono> yards out, a field goal is outside the model&rsquo;s range.</li>
          <li>
            Going for it leads by <Mono>6</Mono> points of WP, a clear call. The coach punts, so the
            call is graded <Mono>−6.0%</Mono>, and since that&rsquo;s at least <Mono>5%</Mono> the model
            disagreed.
          </li>
        </ol>
        <DecisionCard decision={EXAMPLE} />
      </Section>

      <Section id="punt-index" title="The Punt Index">
        <p>
          The Punt Index ranks FBS coaches and teams by the win probability they gave up by kicking or
          punting when the model said go for it. It&rsquo;s measured per game, so a coach with more games
          doesn&rsquo;t rank higher just for coaching more.
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <strong className="font-medium">WP lost</strong> adds up the gap between going for it and what the coach
            chose, on every fourth down where the model recommended going for it and the coach didn&rsquo;t. It&rsquo;s
            divided by games played.
          </li>
          <li>
            <strong className="font-medium">Go rate</strong> is the share of the model&rsquo;s go recommendations the team
            actually went for.
          </li>
          <li>
            Coaches and teams with fewer than <Mono>6</Mono> graded games in the selected seasons are shown greyed out
            and aren&rsquo;t ranked.
          </li>
        </ul>
        <p>
          <strong className="font-medium">Which coach gets credit.</strong> Stats follow the coach of each team-season.
          When a team changed coaches mid-season, the season is split at the change only if the records line up: the
          coaches&rsquo; game counts add up to the team&rsquo;s games, and each new coach was hired before their first
          game. Otherwise those fourth downs count for the team but aren&rsquo;t credited to any coach. We don&rsquo;t
          guess.
        </p>
        <p>
          <strong className="font-medium">Week in Review</strong> uses the same grades. The worst call is the fourth
          down that cost the most win probability. The best call is the one where the coach followed the model and the
          model&rsquo;s edge over the next option was largest.
        </p>
      </Section>

      <Section id="limitations" title="What the model doesn't know">
        <p>This is the section to read before quoting a grade.</p>
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong className="font-medium">It&rsquo;s more aggressive than coaches.</strong> The model
            recommends going for it on about <Mono>58%</Mono> of fourth downs; coaches go on about{" "}
            <Mono>20%</Mono>. We checked the main driver, how little one possession&rsquo;s field position
            moves win probability, against raw outcomes, and the data agree. But it&rsquo;s a strong claim,
            and an outside review is planned before it drives any rankings.
          </li>
          <li>
            <strong className="font-medium">No injuries, personnel, play calls or momentum.</strong> The
            model sees team strength through the spread and Elo, not who&rsquo;s playing today or what the
            offense has been doing well.
          </li>
          <li>
            <strong className="font-medium">Overtime isn&rsquo;t modeled.</strong> Overtime fourth downs are
            not graded, and a tie at the end of regulation counts as a coin flip.
          </li>
          <li>
            <strong className="font-medium">Early-game WP is slightly overconfident.</strong> In the
            first half, mid-range probabilities run <Mono>3</Mono>–<Mono>4</Mono> points too far from{" "}
            <Mono>50%</Mono>.
          </li>
          <li>
            <strong className="font-medium">Trailing teams late in games.</strong> With the game almost
            over, WP is too high for the team that&rsquo;s behind (about <Mono>5%</Mono> predicted where{" "}
            <Mono>1%</Mono> is observed, far from the goal line with <Mono>30</Mono> seconds or less left).
            That makes giving the ball back late look better than it is.
          </li>
          <li>
            <strong className="font-medium">Tries of 4–10 yards.</strong> The conversion model ran about{" "}
            <Mono>3</Mono> points optimistic at these distances in <Mono>2024</Mono>–<Mono>2025</Mono>, which
            nudges it toward going for it.
          </li>
          <li>
            <strong className="font-medium">Long field goals.</strong> Kicking is improving faster than
            the model&rsquo;s trend, so it underrates makes from <Mono>40</Mono>+ yards in recent seasons.
          </li>
          <li>
            <strong className="font-medium">Extra points.</strong> A touchdown counts as exactly{" "}
            <Mono>7</Mono> points.
          </li>
          <li>
            <strong className="font-medium">Historical grades are in-sample.</strong> Seasons{" "}
            <Mono>2013</Mono>–<Mono>2025</Mono> are graded by models trained on those seasons.
          </li>
          <li>
            <strong className="font-medium">Some inputs are estimated.</strong> Before <Mono>2024</Mono>,
            the play-by-play clock often didn&rsquo;t update between plays, so about <Mono>29%</Mono> of graded
            plays use a reconstructed clock (about <Mono>10</Mono> seconds of error in testing). A few games
            never recorded timeouts, and those use typical values.
          </li>
          <li>
            <strong className="font-medium">Some plays are left out:</strong> penalties that wipe out the
            play, garbage time, kneels and spikes, and games whose play-by-play doesn&rsquo;t add up to the
            final score (about <Mono>4%</Mono> of games).
          </li>
        </ul>
      </Section>

      <Section id="data" title="Data and updates">
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Historical play-by-play, betting lines and weather come from CollegeFootballData. Every FBS
            game and every game with at least one FBS team is included, regular season and postseason.
          </li>
          <li>
            Live scores and play-by-play come from ESPN. Team strength and weather for live games are
            captured before kickoff.
          </li>
          <li>
            Completed games are graded after the play-by-play is published and regraded if it&rsquo;s
            corrected. Live grades are provisional until then.
          </li>
          <li>Grades change when the models are retrained. Current models: version <Mono>2.0.0</Mono>.</li>
        </ul>
      </Section>

      <Section id="issues" title="Known issues">
        <p>
          The limitations above are the known modeling issues. If a play looks misread (wrong team,
          wrong down, a penalty graded as a punt), or a grade looks wrong for a reason not listed here,
          open an issue on the{" "}
          <a href={SOURCE_REPO} className="underline decoration-line underline-offset-4 hover:text-bulb">
            source repository
          </a>{" "}
          with a link to the play.
        </p>
      </Section>
    </div>
  );
}
