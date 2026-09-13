# Future improvements

Improvements deliberately **not** being built now. Each item says why it matters and what is known so far, so it can be picked up cold.

Sources of evidence:
- `docs/v1-audit.md`
- `docs/models.md`
- `docs/grades.md`
- `backend/modeling/artifacts/*/metadata.json`

---

## Frontend

Items marked **Done** shipped in Phases 1–2 (`docs/roadmap.md`) and stay here for the record.

1. **Show "not an option" instead of a number.** **Done.**
   - Field goal and punt WP are `null` outside model scope: FG beyond 50 yards to goal, punt inside 30. The v1 app showed a WP for every option, including a field goal from your own 20.
   - The decision card and simulator need a clear empty state for an infeasible option. This also needs the contract change flagged in `docs/models.md` (`wp_field_goal`/`wp_punt` nullable).
2. **Make confidence visible.** **Done.** Every grade stores `confidence` (`clear` / `close` / `toss_up` / `only_option`) and `margin`.
   - A 0.4% edge and a 15% edge should look different.
   - "Toss-up" decisions should never render as a red "mistake" even when the coach went the other way. The stored verdict already handles this (`marginal` below 5%).
3. **Label imputed inputs.** **Done.**
   - Grades carry `timeouts_imputed` (54 games in 2025 had no timeout data) and `clock_source` (`interpolated` for ~45% of 2013–2023 plays).
   - A small "estimated clock/timeouts" marker on historical decision cards is honest and cheap.
4. **Plot the WP chart on every snap.** **Done.** The WP model is trained on downs 1–4, so the game-page chart can use every play, not just fourth downs. Downsample to ~200 points per `api-contract.md`.
5. **Pending-decision card latency.**
   - The live card exists only between the previous play being logged by ESPN and the snap.
   - Show "as of HH:MM:SS" on the card. Hide it instead of showing a stale recommendation once the play is in the play-by-play.
6. **Methodology page content.** **Done.** It needs:
   - the overtime exclusion;
   - the early-game WP overconfidence (3–4 points in Q1–Q2);
   - end-of-game limits;
   - in-sample backfill grades;
   - the measured assumptions table from `docs/models.md`.
7. **Data-quality exclusions.** **Done.** 4% of games fail the score-reconciliation gate and are not graded. Game pages for those games should say "not graded: play-by-play scores don't match the final", not look empty.
8. **Model version on shared links.** (The API returns `model_version` per decision; not shown in the UI yet.) Grades change when models retrain. A deep-linked decision should show the model version it was graded with (`model_versions` is stored per row).
9. **Open Graph image per game.** Sitemap §2 wants the score plus the worst decision as a share image. A Vite SPA can't set per-page OG tags for crawlers. Options:
   - an API endpoint rendering a PNG (Pillow and bundled TTF fonts) plus Vercel edge middleware that injects meta tags for bot user agents;
   - server-render the game page.
10. **Games list filters.** `/games` accepts `team` and `conference`, but the page has no controls for them yet.

---

## Backend

1. **API layer.** **Done** (`app/api`, `app/scheduler.py`, `jobs/game_check.py`, `jobs/process.py`). FastAPI endpoints per `docs/api-contract.md` over the SQLite tables that now exist:
   - `plays_fourth_down`
   - `games`
   - `live_pending`
   - `live_decisions`
   - `pregame_snapshots`
   - `run_log`

   Needs team metadata (names, abbreviations, logos, colors) from CFBD `/teams`, which isn't fetched yet.
2. **Scheduled jobs per `docs/automation.md`.** **Done** (`app/api`, `app/scheduler.py`, `jobs/game_check.py`, `jobs/process.py`).
   - `game-check`: use ESPN for the cheap check; CFBD's free tier can't afford hourly calls.
   - `process`: incremental CFBD fetch for new final games, then dataset build and grading for affected weeks.
   - `pregame_snapshot` before kickoff windows.
   - `live_poll` as an in-app loop, not GitHub Actions cron.
3. **Incremental builds.** **Done** (`app/api`, `app/scheduler.py`, `jobs/game_check.py`, `jobs/process.py`).
   - Today `modeling.build.datasets` rebuilds every season (~2 min), and `jobs.backfill` regrades a whole season.
   - A weekly run should build and grade only games inside the reprocessing window.
4. **Reprocessing window with hash comparison.** **Done** (`app/api`, `app/scheduler.py`, `jobs/game_check.py`, `jobs/process.py`).
   - The write-once CFBD cache suits settled seasons.
   - Current-season plays need timestamped snapshots (`providers/rawstore.py` already supports this) plus a content hash, so corrections trigger regrading.
5. **Reconcile live and batch grades.**
   - ESPN play IDs (e.g. `401856672715`) differ from CFBD play IDs (e.g. `401752794101849903`) for the same play. Map by game ID + period + clock + down/distance/yard line, then replace the live grade with the CFBD grade once it lands.
   - Report how often live and batch recommendations disagree.
6. **ESPN resilience.**
   - Endpoints are undocumented, and community reports mention 403s from 2026-08-05.
   - Add a fallback host (`site.web.api.espn.com`), exponential backoff, and a `stale` flag in the scoreboard envelope when polls fail.
7. **Offense detection when `possession` is null.**
   - In the 2026-09-13 replay every pending fourth down had `possession` populated, so the fallbacks (summary current drive, last play's end team) are untested on real nulls.
   - Add an alert when `offense_unresolved` shows up in `run_log` counts.
8. **Live timeouts.**
   - ESPN scoreboard timeout counts don't appear to reset at halftime; the live path counts timeout plays in the summary instead.
   - Pending-vs-snap agreement was only 53% (offense) and 77% (defense), partly because timeouts get called between detection and snap.
   - Verify against an independent source (broadcast data, or CFBD after it ingests the week, bearing in mind CFBD derives from ESPN). Decide whether end-of-half grades should carry a timeouts-uncertain flag.
9. **Live poll request volume.**
   - Each poll fetches the scoreboard plus a summary for every live game: 16 requests with 15 live games, about 48 a minute at a 20 s cadence against an undocumented API.
   - Fetch summaries only for games on or approaching fourth down, and re-fetch other games' play-by-play every few minutes.
10. **Replay validation coverage.** `analysis/validate_live.py` could match 17 pending states to their plays. Re-run it after a full Saturday capture (`jobs.live_capture` finishes with final summaries) to get a larger sample and to explain the 12 unmatched states.
11. **Coach attribution** (Punt Index, roadmap Phase 3), per the team-season approach in `docs/data-pipeline.md`. Nothing from v1 is reusable.
12. **Artifact storage.** Model artifacts (about 6 MB) are committed. Decide: commit them, or publish to object storage keyed by version and verify the fingerprint on load.
13. **CFBD budget monitor.**
   - Every call is logged with `x-calllimit-remaining`.
   - Surface remaining calls in `/health` and alert below a threshold.
   - Spend so far: 6 calls per pregame snapshot run and 318 for a full historical backfill.
14. **Run-log hygiene.** Make `run_log` counts queryable (not just JSON), and add a check that week totals equal the sum of their games (`data-pipeline.md` validation).
15. **CI.** **Done** (`.github/workflows/ci.yml`). Run `uv run pytest` and `uv run ruff check .` on every push. Tests needing trained artifacts skip cleanly today.
16. **Database size.** The WP series added about 110 MB (1.7M rows); the database is 208 MB. Before Postgres, try:
    - a `WITHOUT ROWID` table;
    - dropping `play_id` from non-fourth-down points;
    - storing each game's series as one compact JSON or blob row.
17. **Scheduler in a multi-worker deploy.** The ticker cache is in memory and jobs assume one process. Scaling out needs the ticker in the database (or Redis) and a job lock.
18. **Retroactive pregame snapshots.** Games processed without a snapshot from before kickoff get one at processing time (`docs/automation.md`). Mark these with a flag so live-versus-batch comparisons can exclude them.

---

## Models

1. **Overtime.**
   - Every model and every grade is regulation-only.
   - Overtime fourth downs are excluded (`exclusions.reason = overtime`).
   - A tie at the end of regulation is scored as a 50/50 coin flip in the option evaluator.

   College overtime is untimed alternating possessions from the 25, with mandatory two-point tries from the third period and alternating two-point plays from the fifth. It needs its own state space rather than more rows in the clock-based WP model:
   - an overtime WP model, or an analytic model on possession outcomes;
   - an end-of-regulation tie value that reflects team strength instead of 0.5;
   - grading for overtime fourth downs.
2. **WP too high for a team losing with the game almost over.** On the 2024–25 holdout:
   - trailing offenses far from the goal (60+ yards) with 30 seconds or less left win about **1%** of the time, but the model predicts about **5–7%**;
   - teams trailing by 1–8 in the final two minutes are predicted **25%** against an observed **29%**, with calibration error 5.7%.

   What's been tried:
   - Lowering `min_child_weight` made no difference.
   - A "trailing yards per second" feature helped a little (7.0% → 5.5% predicted where 1.2% is observed).
   - Explicit kneel-out indicators fixed the matching problem for the *leading* team.

   Things to investigate:
   - Why boosted trees under-fit near-certain losing states. Hessians are small, but `min_child_weight` wasn't binding, so check `max_delta_step`, leaf L2 (`lambda`), and whether the monotone constraints on `yards_to_goal`/`score_diff` stop the needed interactions.
   - An explicit "possessions remaining" estimate (clock ÷ typical drive time, with timeouts), or a rule-based floor/ceiling for states with no plausible path to a score.
   - A calibration layer fit only on final-two-minute states, checked across seasons.
   - Whether reconstructed clocks near the end of halves are off enough to matter (interpolated runs end at period boundaries).

   This matters for grading: it inflates the value of giving the ball back when trailing late.
3. **Early-game WP overconfidence.**
   - Q1–Q2 mid-range probabilities are 3–4 points too confident out of sample (0.35 predicted → 0.39 observed).
   - Five fixes failed: temperature scaling, time-varying calibration, stronger regularization, row subsampling, dropping Elo.
   - The effect varies by season.

   Ideas:
   - pool several seasons of holdout predictions before fitting any calibration;
   - model pregame strength as a single market-implied WP;
   - check whether the spread feature drifted in the portal/NIL era.
4. **Extra point and two-point modeling.**
   - Touchdowns are valued at exactly +7. In the data, 91% of TD rows move the score by 7, 6% by 6 and 2% by 8.
   - Late-game "down 8" and "down 2" decisions depend on the conversion choice.
   - Model PAT/2PT success and the coach's choice, and integrate over them.
5. **Long field goals in recent seasons.**
   - The FG model under-predicts 40+ yard makes in 2024–25 (50–54 yards: 50% predicted vs 56% observed).
   - A linear season trend and a season × distance interaction didn't fix it.
   - Try recency-weighted fits, kicker-specific or team-specific leg strength (from attempt history), or refit each season.
6. **Kickoff and touchback distribution.**
   - After scores, the opponent's start is the median (own 25).
   - The real distribution (p10 own 18, p90 own 35) and kickoff return TDs could be integrated like punts.
7. **Receives the second-half kickoff.** Unused today, and it's known at kickoff from play-by-play (CFBD and ESPN). It matters most for late-Q2 WP.
8. **Conversion model inputs.**
   - Weather and provider-neutral team form added nothing on validation, so the shipped model is situation + Elo.
   - Revisit with play-type tendencies (rush/pass success specifically on short yardage) and quarterback availability once there's a source.
   - 4–10 yard attempts ran ~3 points high in 2024–25.
9. **Punt outcome distribution.**
   - Residual quantiles are bucketed by punt spot only.
   - Condition on wind and returner quality.
   - Model blocks and return TDs explicitly (0.8% of punts) instead of clipping at the goal line.
10. **Clock reconstruction before 2025.**
    - Interpolation of stale clocks was validated by simulation on clean 2024–25 games (9.9 s mean absolute error).
    - Pre-2023 seasons have no snap timestamps for direct validation.
    - Wallclock (present 2018+) could anchor interpolation where the game clock stalls.
11. **Temporal validation hygiene.**
    - 2024–25 test seasons were consulted for two WP design choices, so reported test metrics are slightly optimistic.
    - Hold 2026 out entirely and report 2026 metrics once the season ends.
12. **Retraining cadence.**
    - Define when to retrain (after each season; mid-season only if calibration on graded 2026 decisions drifts past a threshold).
    - Define what a version bump invalidates: all grades, simulator caches, the Punt Index.
13. **Backfill grades are in-sample.** Seasons 2013–2025 are graded by models trained on them. A leave-one-season-out regrade would give honest historical grades for the Punt Index at ~13× the training cost.
14. **Expert review of aggressive recommendations.** The grading layer recommends going for it on 58% of fourth downs (coaches go 20%), including a toss-up on 4th & 10 from your own 20 in a tied Q2.
    - The WP model's low value for field position matches raw outcomes (50% at own 1–20 vs 62% at opponent 1–20 for tied, evenly matched first-half 1st-and-10s).
    - It deserves an outside football-analytics review of a sample of `clear` go recommendations before it drives rankings.
    - Also check the ~3-point conversion overprediction at 4–10 yards, which pushes the same direction.
15. **Conversion outcome when only a touchdown helps.** The option evaluator draws yards gained from the overall conversion distribution. With the clock about to expire, or a touchdown required, teams call different plays. Condition the gain distribution on game state, or model "touchdown on this play" directly.
