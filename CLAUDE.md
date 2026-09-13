# cfb4thdown

College football fourth-down analytics. Every fourth down is graded against a win-probability model.

Ground-up rebuild of [cfb4thdown.com](https://cfb4thdown.com), focused on:

1. **Better product:** "night lights" design, live-first information architecture, mobile-first.
2. **Automated data:** detect, process, and reprocess games without manual weekly work.

## Source of truth

Read the relevant docs before changing behavior:

* `docs/sitemap.md` — pages
* `docs/roadmap.md` — phases, status and exit criteria
* `docs/design-spec.md` — visual system
* `docs/api-contract.md` — API contracts
* `docs/data-pipeline.md` — data processing and grading
* `docs/automation.md` — scheduled jobs

If code and a spec disagree, flag it rather than silently changing the spec.

## Stack

* Frontend: React + TypeScript + Vite + Tailwind + Recharts
* Backend: Python + FastAPI
* Database: SQLite initially
* Deployment: Vercel + Railway
* Data: CollegeFootballData API
* Jobs: GitHub Actions

## Rules

* **Never invent stats.** User-facing numbers must come from real data. Fixtures should use obviously fake values.
* **The model can be wrong.** Present recommendations as model output, not objective truth.
* **Use design tokens.** No arbitrary colors.
* **Cache external data.** User requests never call CollegeFootballData directly.
* **Mobile-first.** Verify at 390px and desktop.
* **Canonical IDs.** Use internal team/game IDs; never join on display names in application code.
* **Keep providers replaceable.**

## Data

CollegeFootballData is rate-limited, and game data can be corrected after initial processing. The pipeline must support batching, reprocessing, and both regular-season and postseason games.

Team logos have inconsistent aspect ratios. Coach attribution can also be unreliable; use the documented team-season approach.

Noteable data quirks
1. For data from CollegeFootballData, the looking at `season` and `week` is not enough as there are
   postseason games. Use the `season_type` column to see if it's postseason or regular.

## Live data

Test ESPN's publicly accessible, undocumented JSON endpoints as a potential live scoreboard/PBP source. Evaluate game-state coverage, update latency, and mapping ESPN games to CFBD games.

If viable, use ESPN for live data and CFBD for historical/model data. Keep the live provider replaceable.

## Current phase

See `docs/roadmap.md` for status. Backend foundations (data, models, grading, backfill, live prototype) are built; **Phases 1–2** are deployed and **Phase 3** is built (ranking pages carry an "under review" notice until the review gate passes). Next: the review gate, then **Phase 4 — simulator**.
