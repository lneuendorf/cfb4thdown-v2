import { Link } from "react-router-dom";
import { Notice, PageHeader } from "../components/PageHeader";

// Pages whose data isn't served yet (docs/roadmap.md). Each states the page's job from
// docs/sitemap.md so the nav is honest about what's coming.

function NotYet({ eyebrow, title, job, phase }: { eyebrow: string; title: string; job: string; phase: string }) {
  return (
    <div>
      <PageHeader eyebrow={eyebrow} title={title}>
        {job}
      </PageHeader>
      <Notice>
        Not built yet. It arrives in {phase}. Meanwhile,{" "}
        <Link to="/methodology" className="text-text underline decoration-line underline-offset-4">
          read how the grades work
        </Link>
        .
      </Notice>
    </div>
  );
}

export const WeekPage = () => (
  <NotYet
    eyebrow="Week in review"
    title="Week in review"
    job="The week's worst and best calls, and win probability surrendered by conference."
    phase="Phase 3"
  />
);

export const PuntIndexPage = () => (
  <NotYet
    eyebrow="The Punt Index"
    title="The Punt Index"
    job="Coaches ranked by win probability surrendered through conservative fourth-down decisions."
    phase="Phase 3"
  />
);

export const SimulatorPage = () => (
  <NotYet
    eyebrow="Simulator"
    title="Decision simulator"
    job="Set up any fourth down and see what the model says."
    phase="Phase 4"
  />
);

export const NotFoundPage = () => (
  <div>
    <PageHeader eyebrow="404" title="Not found">
      There&rsquo;s no page at this address.
    </PageHeader>
    <Link to="/" className="inline-flex min-h-[40px] items-center text-body underline decoration-line underline-offset-4">
      Back to the scoreboard
    </Link>
  </div>
);
