# Roadmap

The build order for cfb4thdown: what each phase delivers, what's done, and what has to be true before moving on. It replaces the "Build order" section that used to live in `docs/sitemap.md`.

Pages and their jobs are in `docs/sitemap.md`. Deferred ideas that aren't scheduled into a phase are in `docs/future-improvements.md`.

**Status as of 2026-09-13** (Phases 1–2 deployed: Railway API, Vercel site)

| Phase | Name | Status |
|---|---|---|
| 0 | Scaffolding and specification | Done |
| 1 | Spine (design system, static Methodology) | Deployed |
| 2 | Data served (API, jobs, game page, weekly scoreboard) | Deployed; OG images not built |
| 3 | Derived (Punt Index, Week in Review) | Built; pages carry an "under review" notice until the review gate passes |
| 4 | Simulator | Built |
| 5 | Backfill 2013–2025 | Done early (in-sample grades) |
| 6 | Live grading (pending-decision card) | Prototype built and replay-tested; not in production |
| 7 | Model improvements | Planned |

Phases 0–5 keep their original numbers. Live grading moved out of Phase 2 into a new Phase 6, following `docs/v1-audit.md` §5. Phase 7 is new.

---

## Principles for ordering

- **Ship something real early, but never a wrong number.** Pages built on graded data wait for the review gate (below).
- **Batch before live.** Live grading needs everything batch grading needs, plus polling, fragile ESPN parsing and reconciliation with the later CFBD grade.
- **Each phase deploys.** A phase isn't done until it's running somewhere, not just merged.
- **Specs change in the same PR as the code that contradicts them** (`CLAUDE.md`). The open spec conflicts listed under each phase are part of that phase's scope.

---

## Phase 0 — Scaffolding and specification · Done

- Repo layout, `CLAUDE.md`, agents, commands and hooks.
- Specs: `sitemap.md`, `design-spec.md`, `api-contract.md`, `data-pipeline.md`, `automation.md`.
- v1 audit (`docs/v1-audit.md`): verdict was retrain the models; cut live grading from the first data phase.

## Phase 1 — Spine · Built; not deployed

**Goal:** prove the design system with a deployed site that has no data dependencies.

**Scope**
- `frontend/` scaffold: React, Vite, TypeScript strict, Tailwind, Recharts.
- Tokens in `frontend/src/styles/tokens.css`, exposed through Tailwind.
- Shared components: LightBank, TeamMark, ScoreRow, DecisionChip, DecisionCard, StatStrip.
- Methodology page as static content.
- Vercel deploy.

**Must account for, from work already done**
- Decision cards need states for:
  - an infeasible option (`null` field goal or punt WP);
  - confidence (`clear`, `close`, `toss_up`, `only_option`);
  - verdict (`correct`, `marginal`, `mistake`).
- Methodology must cover the model's limitations (`docs/models.md`, `docs/grades.md`):
  - overtime isn't modeled;
  - early-game WP is overconfident;
  - end-of-game WP is weak for trailing teams;
  - historical grades are in-sample;
  - measured assumptions;
  - reconstructed clocks.
- Components render from fixtures with obviously fake values (`CLAUDE.md`).

**Built (2026-09-12)**
- `frontend/`: Vite, React 18, TypeScript strict, Tailwind with the palette replaced by tokens, self-hosted Inter and JetBrains Mono.
- Components: LightBank, Ticker, TeamMark, ScoreRow, DecisionChip, DecisionCard, PendingDecisionCard, OptionWps, StatStrip, RankedRow, PageHeader, Layout with the mobile "More" menu.
- `LiveScoreboardView`: the home page as a presentational view of `GET /scoreboard/live`, with loading, error, stale and empty states, and a fixed-height pending slot.
- Methodology page, with a worked example using illustrative numbers.
- Placeholder pages for the other routes, each stating its job and phase.
- Dev pages: `/dev/components` (fake fixtures) and `/dev/live` (real ESPN captures from `analysis.live_fixtures`).
- Checks: `npm run typecheck`, `npm test` (9 tests), `npm run lint:tokens`, `npm run build`. Dev code is absent from the production bundle.
- Verified at 390px and 1280px: no horizontal overflow, no text under 11px, no pending-card layout shift between polls.
- `vercel.json` for SPA rewrites.

**Not done**
- The Vercel deploy. It needs the project linked to a Vercel account.
- Design-spec questions, below.

**Design-spec questions raised while building**
- **Amber has several meanings on the live page.** The spec's own components use it for the ticker, light bank, leading score, active nav, FG chip and marginal verdict. The pending card also uses it, as the live accent. Decide which of these give up amber.
- **Light bank size.** The bank for live games shows rows of 12 bulbs (one lit per live game). A Saturday with 60 live games makes 5 rows.
- **Team colors** from the API aren't used anywhere, per the verdict-color rule.

**Exit criteria**
- `/design-check` is clean and every component is verified at 390px and desktop.
- Methodology includes one worked example, but with fake numbers until the review gate passes.
- The site deploys.

## Phase 2 — Data served · Built; not deployed

**Goal:** real graded data on the site for completed games.

**Built before this phase** (see `docs/models.md`, `docs/grades.md`)
- CFBD ingestion with write-once and timestamped raw caches, and a call log.
- Data build with Elo, pre-snap states and data-quality gates.
- Retrained models, v2.0.0.
- Option evaluator and grading (`app/grading.py`, `app/decisions.py`).
- SQLite store with `run_log`; `jobs.backfill` and `jobs.pregame_snapshot`.

**Built in this phase (2026-09-13)**
1. **Contract conflicts resolved** in `docs/api-contract.md`:
   - nullable `wp_field_goal`/`wp_punt`, and `confidence: only_option` with `margin`;
   - `season_type` as a query parameter, with CFBD week numbers declared;
   - Decision `id` is the source play id, with `source`;
   - data-quality flags `clock_source`, `timeouts_imputed`, `model_version`.
2. **Team metadata:** `jobs.teams` loads CFBD `/teams` into `teams` (1,933 teams, one call).
3. **FastAPI service** (`app/api/`):
   - endpoints `/scoreboard/latest`, `/scoreboard/week/:season/:week`, `/games`, `/games/:id`, `/teams`, `/ticker`, `/health`;
   - freshness envelope, `stale` flag, Cache-Control, and contract-shaped errors.
4. **Shared grading and incremental processing:**
   - `app/batch.py` is shared by the backfill and `jobs.process`; the refactored 2025 backfill reproduced the earlier grades exactly;
   - `jobs.process` handles per-game hashes, the 7-day reprocessing window, and per-game status in `game_sources`;
   - the 2026 season so far (177 games) is graded with 8 CFBD calls.
5. **WP series:** `wp_series` covers every snap for every graded game, 2013–2026 (about 1.7M points).
6. **Scheduled jobs:**
   - `jobs.game_check` (ESPN only) and an in-process scheduler (`app/scheduler.py`) running game check → process / pregame snapshot hourly, teams weekly, and the ticker;
   - it runs in the API process, not GitHub Actions (`docs/automation.md` explains why);
   - Elo history and venues come from the database, so the server doesn't need the raw cache.
7. **Pages:**
   - home page as the latest graded week (stats, ranked feed linking to plays);
   - game page with score, totals, WP chart with verdict-ringed fourth downs, chronological decisions with `#play-` anchors, and not-graded explanations;
   - games list by week;
   - site-wide ESPN score ticker, polling only while games are live.
8. **CI:** `.github/workflows/ci.yml` runs ruff, pytest, typecheck, frontend tests, token lint and build.
9. **Deploy prep:** `backend/Dockerfile` (API and scheduler in one process, SQLite on a `/data` volume).
10. **Tests:** 11 new backend tests (API contract, `game_check`, `process` targeting, downsampling, ticker) and 3 game-page tests.

**Not done**
- **Railway and Vercel deploys.** They need accounts linked, and the 208 MB database uploaded to a volume. The Docker image hasn't been built here (no Docker daemon).
- **Open Graph image per game.** This needs server-rendered meta tags or edge middleware, because the SPA can't set per-page OG tags for crawlers. Deferred.
- **Exit criteria not yet observed.** "A completed Saturday graded by Sunday morning with no manual steps" needs the deployed scheduler running through a Saturday. Locally, the pieces ran end to end on 2026-09-12's games.

**Decisions made here**
- The home page shows the latest graded week until live grading (Phase 6); the nav says "Scoreboard".
- A game graded without a snapshot from before kickoff gets a retroactive pregame snapshot (`docs/automation.md`).
- The wordmark moves to the footer on phones so the four primary nav items fit at 390px.

**Not in this phase:** the pending-decision card and live WP deltas (Phase 6).

**Exit criteria**
- A completed Saturday is graded and on the site by Sunday morning, with no manual steps.
- `run_log` shows exclusion counts. Validation flags are triaged (the 2–20 per-game check needs the spec fix).
- Game pages for games that fail the score-reconciliation gate say why they're ungraded. *(Built.)*
- CFBD usage stays within the Tier 1 budget; watch `x-calllimit-remaining`.

## Review gate — before any public rankings or headline claims

The grading layer recommends going for it on 58% of fourth downs; coaches go on 20%. The field-position values behind this match raw outcomes, but the claims are strong. Before Phase 3 goes public:

- An outside football-analytics reviewer checks a sample of `clear` go recommendations and the textbook-situation table (`docs/grades.md`).
- Decide whether published historical grades stay in-sample (disclosed) or get a leave-one-season-out regrade (`future-improvements.md` Models #13).
- Decide whether the ~3-point overprediction of conversion at 4–10 yards needs fixing first.

Phase 2 pages can go live before the gate if every grade is labeled as model output and there are no league-wide rankings.

## Phase 3 — Derived · Built (under review)

**Goal:** the named metric and the weekly habit.

**Built (2026-09-13)**
- **Coach attribution** (`jobs.coaches`, one CFBD call, weekly in the scheduler):
  - team-season based, from CFBD `/coaches`;
  - mid-season changes split only when game counts sum and hire dates fit the schedule, and coaches who took over mid-season are flagged;
  - otherwise the team-season is unattributed, with a reason in `coach_attribution_issues`;
  - result: 1,691 sole-coach team-seasons, 185 split segments, 45 unattributed team-seasons (2013–2026).
- **Aggregates computed on request** (`app/api/aggregates.py`):
  - no materialized tables, so rankings reproduce from stored grades;
  - week totals are sums of their games by construction;
  - a model version bump changes every aggregate at once.
  - This replaces the planned Tuesday `week-in-review` job.
- **Punt Index API and page:**
  - coaches or teams, WP lost per game or go rate, season range, conference, current coaches only;
  - URL-encoded filters, and small samples shown greyed and unranked;
  - a detail page with a season table.
- **Week in Review API and page** (`/week`, `/week/:season/:week`):
  - headline WP lost per game, worst and best call, conference bars, Punt Index movers;
  - optional commentary (`jobs.commentary`), and every fourth down behind "show all".
- **Methodology:** a Punt Index section with the definitions and the attribution rule.
- **Tests:** 7 new backend tests (attribution rules, Punt Index, Week in Review) and 1 frontend test.

**Decisions made here**
- `wp_lost` is **per game**, not a season total, so ranges and shortened seasons compare fairly.
- The Week in Review headline is **WP lost per game**. A league-wide sum of WP percentages (for example −373%) doesn't read as a number; the total stays in the API.
- Week in Review and the Punt Index cover FBS offenses only.

**Still gated:** the review gate below. Every ranking page shows an "under review" notice until it passes.

**Not done**
- Conference and top-25 filters on the home feed (top-25 needs a rankings source).
- A trend chart on the detail page; the season table carries the trend.

**Exit criteria**
- Rankings reproduce from stored grades. *(By construction.)*
- Week totals equal the sum of their games. *(By construction.)*
- A model version bump regenerates every aggregate. *(By construction.)*

## Phase 4 — Simulator · Built

**Goal:** make the model something people can play with.

**Built (2026-09-13)**
- **`GET /simulate`** (`app/api/simulate.py`):
  - runs the grading option evaluator (about 70 ms warm), memoized per model version, and is CDN-cacheable;
  - validates inputs and returns contract-shaped 400s.
- **Decision: server endpoint, not a precomputed table.** About 25 model inputs make a full table impractical, and a reduced one would silently fix team strength, timeouts and weather.
- **Defaults for unexposed inputs:**
  - team strength is one spread slider, mapped to both Elo ratings by inverting the spread imputer around the FBS base rating;
  - weather and elevation are the training medians, outdoors, at the latest model season;
  - timeouts default to 3 each and can be changed.
  - All defaults are echoed in the response.
- **Similar situations:** graded FBS fourth downs since 2013 with the same distance band, yards to goal ±5, score band and quarter. It reports what coaches did, what the model said, and the 5 most recent examples linking to their plays.
- **Page `/simulator`:**
  - every input in the URL, and opens on 4th & 2 at the opponent 40, down 4 with 6:00 left;
  - result panel with option bars ("not an option" for infeasible ones), confidence and margin, conversion and FG odds, and the punt's expected start;
  - a pinned result bar on phones, and copy link.
- **Tests:** 3 backend and 1 frontend.

**Decisions made here**
- **Both scores instead of a score differential.** The WP model uses each score, not only the difference.
- **One spread slider instead of separate offense and defense ratings.** One number keeps all four models consistent.

**Not done**
- `conversion_rate` in similar situations. Conversion outcomes aren't stored with grades yet; that needs a small backfill column.

## Phase 5 — Backfill · Done early

- 160,357 fourth downs graded for 2013–2025 (`jobs.backfill`, ~20 s from processed data).
- **Caveat:** grades are in-sample, because the models were trained on these seasons.
- **Remaining:** re-run after every model version bump, and resolve the in-sample question at the review gate.

## Phase 6 — Live grading · Prototype built

**Goal:** the pending-decision card, meaning the recommendation before the snap.

**Already built:**
- ESPN provider with raw snapshots;
- `jobs.live_capture`;
- `jobs.live_poll` (`--once`, `--loop`, `--replay`), writing `live_pending` and `live_decisions`;
- `analysis/validate_live.py`.

In the 2026-09-13 replay, offense, field position, distance and score matched the play that followed (17 of 17). Timeouts matched 53–77%.

**Scope**
1. The live poller as a third scheduler loop in the API process (`app/scheduler.py`), active only while games are live.
2. Request budget: fetch summaries only for games on or near fourth down (today it's about 48 requests a minute with 15 live games).
3. ESPN resilience: fallback host, backoff, `stale` flag.
4. A reliable timeouts source, or flag timeouts as uncertain late in halves.
5. Link ESPN play IDs to CFBD play IDs, and replace live grades with batch grades once CFBD publishes the week. Report how often they disagree.
6. `/scoreboard/live` with `pending` and ticker WP deltas; the home page in live mode.
7. Validation on at least one full Saturday, with a larger matched sample and the unmatched cases explained.

**Depends on:** Phase 2 (pregame snapshots on schedule, API) and the review gate.

**Exit criteria**
- A full Saturday runs unattended.
- Pending cards appear and clear correctly.
- Live and batch recommendations agree on a stated share of plays, with every disagreement explained.

## Phase 7 — Model improvements · Planned

From `docs/future-improvements.md` (Models), in suggested order:

1. WP too high for trailing teams with the game almost over (Models #2).
2. Overtime: an overtime WP model, an end-of-regulation tie value, and grading overtime fourth downs (Models #1).
3. Extra point and two-point modeling (Models #4).
4. Conversion outcome when only a touchdown helps (Models #15), plus the 4–10 yard overprediction.
5. Early-game WP overconfidence (Models #3).
6. Long field goals in recent seasons (Models #5).
7. A 2026 true holdout, and a retraining cadence and invalidation policy (Models #11, #12).

**Every model change:**
- bumps the version (`modeling/inference.py`, artifact paths);
- reruns the backfill;
- regenerates aggregates;
- invalidates simulator caches;
- updates `docs/models.md`.

Items 1 and 4 affect end-of-game grades most, so do them before the Punt Index gets real attention.

---

## Open questions that affect the plan

- **Hosting the database:** SQLite on a Railway volume (current design), or Postgres? The graded DB is 208 MB with the WP series.
- **Artifacts:** commit the 3.2 MB of model artifacts, or publish them by version?
- **ESPN dependency:** is an undocumented API acceptable for production live data, or should Phase 6 wait for a licensed feed?
- **Review gate:** who performs the review, and what outcome would change the model versus only the copy?
