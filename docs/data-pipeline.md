# Data pipeline

Raw play-by-play in, graded fourth-down decisions out.

```
CollegeFootballData API
        ↓  fetch
   raw plays (cached to disk, immutable)
        ↓  filter
   fourth-down situations
        ↓  model
   wp_go / wp_punt / wp_field_goal
        ↓  grade
   recommendation, verdict, wp_delta
        ↓  aggregate
   team-season, coach-season, week rollups
        ↓
   SQLite → API cache
```

## Principles

**Raw data is immutable and cached to disk.** Every upstream response is written to `data/raw/{season}/{week}/{game_id}.json` before anything touches it. Reprocessing never re-fetches. This makes model changes cheap — retrain, replay from disk, no API calls.

**Processing is idempotent.** Running the pipeline twice on the same input produces the same output. Every stage is safe to re-run.

**Failure is per-game, not per-run.** One malformed game doesn't stop the batch. Log it, flag it, continue.

---

## Stage 1 — fetch

Input: season, week. Output: raw JSON on disk.

- Batch requests. CollegeFootballData allows roughly 200/hour; a full week is ~60 games. **Never one request per game in a loop** — use the bulk plays endpoint filtered by week.
- Exponential backoff on 429 and 5xx: 1s, 2s, 4s, 8s, 16s, then give up and flag the week.
- Skip games already on disk **unless** they're inside the reprocessing window (below).
- Record the fetch timestamp alongside the payload.

### Reprocessing window

Play-by-play gets corrected after the fact — scoring changes, misattributed plays, clock fixes. A game processed once is not processed forever.

- Games less than **7 days** old are re-fetched on every run and compared by hash.
- If the hash changed, reprocess and invalidate downstream caches for that game, its week, and the affected team/coach aggregates.
- After 7 days, a game is considered settled and only re-fetched on an explicit manual trigger.

Corrections are common enough that skipping this will produce numbers that quietly disagree with every other source.

---

## Stage 2 — filter

From raw plays, keep situations where `down == 4` and the play is a real decision point.

**Exclude:**
- End-of-half and end-of-game kneel or clock situations where the decision isn't meaningful
- Plays with a pre-snap penalty that negated the down
- Garbage time — configurable, default is WP outside 1-99% with under 5 minutes left
- Games missing yard line or clock data

Every exclusion is logged with a reason. Exclusion counts go in the run report — a sudden jump means upstream changed something.

---

## Stage 3 — model

Four components combine into the decision.

### Win probability

Given game state (yards to goal, down, distance, score differential, time remaining, timeouts, possession), estimate probability the possessing team wins.

This is the foundation — everything else is expressed in its units.

### Fourth-down conversion

Probability of gaining the required distance, as a function of distance and field position. Optionally adjusted by offense and defense quality.

### Field goal

Probability of making from a given distance.

### Punt

Expected resulting field position, including touchbacks and returns.

### Combining

```
wp_go        = p_convert · WP(first down at new spot) + (1 − p_convert) · WP(turnover on downs)
wp_field_goal = p_make · WP(made, kickoff) + (1 − p_make) · WP(miss, opponent ball at spot)
wp_punt       = E[WP(opponent ball at resulting field position)]

recommendation = argmax of the three
wp_delta       = wp(actual decision) − wp(recommendation)
```

`wp_delta` is therefore always ≤ 0 when the coach deviated, and exactly 0 when they followed the model. **Correct calls that gained WP relative to a plausible alternative are presented as positive in the UI** — that's a display-layer transformation, documented in the API contract, not a different calculation.

### Model versioning

Every model carries a semantic version. It's stored on every graded decision and returned by `/health`. Changing the model requires bumping the version, which invalidates the simulator cache and triggers a full replay from disk.

---

## Stage 4 — grade

Attach `recommendation`, `decision`, `wp_delta`, `verdict`.

Verdict thresholds live in `backend/app/grading.py` as named constants. The 5% mistake threshold appears in exactly one place.

---

## Stage 5 — aggregate

Rolled up after each run:

- **Team-season:** go rate when recommended, total WP lost, fourth downs faced
- **Coach-season:** same, derived from team-season via the coach-team mapping
- **Week:** totals, worst call, best call, conference breakdown
- **Punt Index:** ranked coach and team lists across a season range

### Coach attribution

This is the messiest part of the system. Coaches change mid-season, interim coaches appear, and the API's coach records lag.

- Coach stats derive from **team-season**, not from individual plays.
- A mid-season change splits the season into two coach-season records, boundaries from the coaching change record.
- Interim stretches are attributed to the interim, flagged `is_interim`.
- When attribution is genuinely unknown, record it as unattributed rather than guessing. **Never guess a coach.**

---

## Storage

SQLite at `backend/data/cfb4thdown.db`. Tables mirror the pipeline stages: `games`, `plays_fourth_down`, `team_seasons`, `coach_seasons`, `coaches`, `coach_tenures`, `weeks`, `run_log`.

Built so far (`backend/app/db.py`):
- **Grading:** `games` (every game since 2000, for Elo replay), `plays_fourth_down`, `exclusions`, `wp_series`.
- **Current season and live:** `game_sources` (per-game processing status and play-by-play hash for the reprocessing window), `pregame_snapshots`, `live_pending`, `live_decisions`.
- **Reference and logging:** `teams`, `venues`, `run_log`.

The coach and aggregate tables arrive with Phase 3.

The raw layout differs from the one described above; `docs/models.md` "Conflicts" item 2 explains why. Current-season processing is in `docs/automation.md`.

`run_log` records every pipeline execution: start, end, games fetched, games reprocessed, decisions graded, exclusions by reason, errors. This is how you debug a number that looks wrong three weeks later.

Migrate to Postgres if the DB exceeds a few GB or concurrent writes become a problem. Not before.

---

## Validation

Before a run's output is committed:

- Fourth downs per game should fall between 2 and 20. Outside that, flag the game.
- Sum of WP across the three options is not meaningful, but each must be in [0, 1].
- Every graded decision must reference a game that exists.
- Week totals must equal the sum of their games.
- Compare the run's aggregate WP lost against the previous run. A change over 20% on settled data means something broke.

Validation failures flag and continue. They don't halt the run, but they do surface in the report.

---

## Backfill

Separate one-off script, not part of the scheduled pipeline.

```bash
uv run python -m jobs.backfill --from 2013 --to 2025
```

Run it season by season, respecting rate limits — expect a few hours. Raw data lands on disk, so re-grading all history after a model change is fast and free.
