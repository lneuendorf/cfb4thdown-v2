# Models v2.0.0

Retrained 2026-09-12 from CollegeFootballData play-by-play for 2013–2025. The recommendation to retrain came from `docs/v1-audit.md`. This doc covers:

- the data fixes made before training;
- what each model is and how well it does;
- known limitations;
- where the written plan now disagrees with what was built.

How the models are combined into graded decisions, the 2013–2025 backfill, the comparison with v1 and live inference are in `docs/grades.md`. Deferred work is in `docs/future-improvements.md`.

Everything here is **model output, not ground truth**. The numbers below are the evidence for trusting it, and the limitations say where not to.

Code lives in `backend/modeling/`. Artifacts are in `backend/modeling/artifacts/{model}/2.0.0/`: a model file plus `metadata.json`, which holds features, tuning, holdout metrics, calibration tables and a data fingerprint.

---

## Summary

| Model | Predicts | Inputs | 2024–25 holdout | Reference |
|---|---|---|---|---|
| Win probability | P(offense wins) from any pre-snap state, downs 1–4 | score, clock, field position, down/distance, timeouts, spread, two Elos, 3 end-of-game indicators, 2 kneel-out clocks | log loss 0.340, Brier 0.111, calibration error 1.1% (261,728 states) | v1: 0.374 log loss on a random split of 1st-and-10/4th-down only; not comparable |
| Fourth-down conversion | P(gain the distance or TD, no turnover) | distance, yards to goal, score×time, home/away/neutral, two Elos | log loss 0.632, calibration error 2.1% (6,933 attempts) | distance-only baseline 0.636 |
| Field goal make | P(make) | yards to goal (+ squared), offense Elo, wind, precipitation, elevation, indoors, season trend | log loss 0.490, calibration error 2.2% (4,932 attempts) | — |
| Punt result | Receiving team's yards to goal on its next snap | punt spot, two Elos | RMSE 12.4 yds, MAE 8.4 yds (14,202 punts) | yard-bucket mean baseline RMSE 12.1 on validation |

Measured post-play assumptions for the decision layer live in `artifacts/decision_assumptions/2.0.0/assumptions.json` (see "Decision assumptions" below).

**Holdout protocol.**

- **Tuning:** hyperparameters are tuned on 2013–2021 and validated on 2022–23.
- **Holdout scoring:** a refit on 2013–2023 is scored once on 2024–25.
- **Shipped artifacts:** refit on all of 2013–2025 with the same hyperparameters.
- **Reproducibility:** tuning is seeded, and a re-run reproduced the WP model exactly.

---

## Reproduce

```bash
cd backend
uv sync
uv run python -m modeling.ingest            # 318 CFBD calls, write-once raw cache (~6 min)
uv run python -m modeling.build.datasets    # games, Elo, spreads, weather, pre-snap states, team form (~2 min)
uv run python -m modeling.train.wp          # ~7 min
uv run python -m modeling.train.conversion
uv run python -m modeling.train.field_goal
uv run python -m modeling.train.punt
uv run python -m modeling.train.assumptions
uv run python -m jobs.backfill --from 2013 --to 2025   # grades into data/cfb4thdown.db (~20 s)
uv run pytest && uv run ruff check .
```

- **Scope.** Every CFBD request uses `classification=fbs`. That returns exactly the games with at least one FBS team; I verified it covers all 96 week-1 2025 games, including the 48 FBS-vs-non-FBS games. Only regular season and postseason are fetched.
- **Environment.** Pinned in `uv.lock`: Python 3.12, xgboost 3.4.1, pandas 3.0.5, numpy 2.5.3.

---

## Data fixes (done before any training)

### D1. Elo processed chronologically

**Problem (audit B3/B4).** v1 processed Elo by week number, which caused two errors:
- postseason games got preseason ratings;
- bowl results leaked into regular-season ratings from week 2 on.

**Fix.** Ratings update game by game in kickoff order and are keyed by `game_id`, so `season_type` can't collide. Ratings regress toward the classification baseline at each team's first game of a season.

**Tuning.** Grid-searched on 2003–2012 outcomes, after burn-in from 2000:

| Parameter | Value |
|---|---|
| K | 35 |
| Home field | 55 |
| Season regression | 20% |
| FCS starting rating | 1000 |

**Result.** Game-outcome log loss on 2013–2025 is 0.507, versus 0.616 with v1's parameters. Neighbouring grid points are within 0.001.

**Live parity.** `elo.ratings_before` (used for pregame snapshots) reproduces the training Elo exactly: 0.0 difference on 120 random games.

**Tests.** `tests/test_elo.py` asserts that a bowl game uses the end-of-season rating and that a bowl result cannot change an earlier game's pregame rating.

### D2. Pre-snap scores

**Problem (audit B1).** CFBD scores on a play row are post-play: 93–100% of made FGs per season carry the +3 on the kick row itself.

**Fix.** The pre-snap score is the previous row's post-play score.

**Alternatives tested.** I compared rules by how often a non-scoring play leaves the score unchanged:

| Rule | Agreement, 2022–25 |
|---|---|
| Previous row (chosen) | 98.5–99.1% |
| Previous scrimmage row | slightly lower |
| Running maximum | 93–95% |

**Remaining bad rows.** Rows where the score then decreases (about 0.5%) are marked invalid.

### D3. Pre-snap clock

**Problem.** CFBD records the snap clock in some games and the end-of-play clock in others.

**Fix.** The pre-snap clock comes from, in order of preference:
1. the `(MM:SS)` snap time in the play text, when present (35% of 2025 plays; about 0% before 2023);
2. an interpolated clock, for plays inside a stale-clock run (D12);
3. the recorded clock, for games classified as snap-clock recorders from their post-timeout plays (stale runs are not counted as evidence);
4. otherwise, the recorded clock plus the median play duration for that play type, capped at the previous row's clock. Durations are fit on 2025 and stored in `data_build/play_durations.json`.

**Validation, 2025 holdout games** (snap times hidden from the rule):

| Clock rule | Mean absolute error | Bias | Within ±3 s |
|---|---|---|---|
| Recorded clock (what v1 used) | 6.35 s | −5.7 s | 26% |
| Reconstruction | 3.26 s | −0.9 s | 70% |

After D12 was added, the same check (with durations in-sample) gives 3.44 s vs 6.39 s.

### D4. Game-level quality gate

A game is used for training only if both hold:
- the highest play-by-play score equals the official final score;
- at least 95% of non-scoring plays leave the score unchanged.

Many 2013 touchdowns are typed "Rush" with TOUCHDOWN only in the text; the gate accounts for that. Some 2013 games also post the score one play early, and the gate removes the worst of them.

Result: **10,725 of 11,170 games (96%)** pass, ranging from 769/848 in 2013 to 871/934 in 2025. Per-season counts are in `data_build/play_quality.json`.

### D5. Timeouts

- **Semantics.** Timeout rows already carry the decrement (99.5%), so a scrimmage play's own values are its pre-snap values.
- **Sporadic nulls** are forward-filled per team within the half.
- **Unknown games.** 54 games in 2025 (plus 2 earlier) have no timeout values and no timeout rows to rebuild from. They are marked `timeouts_known = false` and excluded from WP training; forward-filling would have given every team 3 timeouts all game.
- **Grading those games** uses median timeouts by half and minute, flagged `timeouts_imputed`.

### D6. IDs

- **Team IDs.** Offense and defense names are resolved against that game's two teams only; zero rows failed in 2013–2025. No model input joins on display names.
- **ESPN mapping.** ESPN and CFBD share team IDs (172 of 172 checked) and game IDs (86 of 86 checked for 2026, 0 home-team mismatches).
- **Week numbers don't align.** CFBD's 2026 "week 2" is ESPN's week 3. Map by `game_id`, never by week.
- **Play IDs differ** between ESPN and CFBD (see `docs/grades.md`).

### D7. Kneel-out simulator uses college rules

v1 applied an NFL two-minute warning. College football has none. Tested in `tests/test_features.py`.

### D8. Weather and venue

- **Plausibility bounds.** Out-of-range values become missing rather than being clipped:

  | Field | Kept range |
  |---|---|
  | Temperature | −10 to 115 °F |
  | Wind | 0 to 60 mph |
  | Precipitation | 0 to 3 |

- **Indoor games:** 70 °F, no wind, no precipitation. Indoors comes from the weather record, falling back to the venue dome flag.
- **Missing outdoor weather** (1.8% of 4th downs): training-set outdoor medians, stored in the assumptions artifact for live use.
- **Live availability.** CFBD populates weather rows for games that haven't been played yet: all 75 of 2026 week 3 had rows a week early, and all 80 of 2026-09-12's games had weather at snapshot time. So the one model that uses weather (FG) has a pre-game source.

### D9. Spread

- **Source:** median closing spread across providers, from the home perspective (negative means home favored, confirmed against CFBD's formatted spread).
- **Missing spreads** (0.8% of WP rows) are imputed from Elo difference plus home field (MAE 5.15 points), stored in `data_build/spread_imputer.json`. Unlike v1's pickle, it has provenance.

### D10. Labels checked against the next recorded state

- **Conversion label** (TD, or gained the distance without a turnover) agrees with the next state 98.2% of the time. The disagreements I inspected were mostly the check's own blind spots: a pick-six looks like a first down for the offense after the kickoff.
- **Punt target** is the receiving team's next pre-snap yards to goal, or 0 for a return TD. Excluded:
  - 3,128 punts where the kicking team kept the ball;
  - 300 punts where the half ended.

### D11. Provider-neutral team form (built, not shipped)

v1's conversion model depended on CFBD-proprietary metrics (PPA-based strength and CFBD advanced stats), which conflicts with "keep providers replaceable".

I built a replacement: opponent-adjusted rush and pass success rates from our own play-by-play, via weekly ridge fits on prior games only. Pregame matchup ratings correlate 0.39–0.44 with realized success.

It did not improve any model on validation, so no shipped model uses it and no model needs CFBD-derived metrics. The code is in `build/team_form.py`.

### D12. Stale clocks interpolated (found while building the grading layer)

**Problem.** In 2013–2023, 40–60% of rushing plays carry the *same* clock as the next snap. CFBD's clock only updated intermittently: one 2016 game stamps 15:00 on five straight plays through a punt, then 13:20 on the next seven. Every play takes time, so identical clocks on consecutive scrimmage plays are stale. The problem nearly disappears in 2024 (16%) and 2025 (11%).

This broke two things silently:
- time features in WP training;
- my snap-clock classifier in D3, which read stale runs as snap-time recording. A short first-down run followed by the next snap showed a median of 0 seconds.

**Fix.**
- Within each run, keep the first clock.
- Space later plays toward the next recorded clock, weighted by how much clock each play type typically uses. Weights are measured on 2024–25 games with under 3% repeats (`data_build/clock_interpolation_weights.json`): rush 35 s, completed pass 29 s, incompletion 7 s, and so on.
- Interpolated plays are flagged (`clock_interpolated`, `clock_source = interpolated`). Stale runs are excluded as clock-semantics evidence.

**Validation.** Stale runs were simulated on 1,212 clean 2024–25 games using the empirical run-length distribution from 2017. Mean absolute error on affected plays:

| Method | Mean abs error |
|---|---|
| Stale clock (no fix) | 84.2 s |
| Linear interpolation | 14.8 s |
| Play-type weighted (chosen) | 9.9 s |

After the fix, a short first-down run is followed by the next snap about 33 s later in both 2017 and 2025.

**Scale.** 38k–71k plays per season were interpolated in 2013–2023, and 14k–21k in 2024–25. All models were retrained afterwards.

### D13. Play types added for 2025 and ESPN

CFBD's 2025 data labels 737 fourth-down punts "Punt Return" and some fumbles "Fumble". Those types were categorized "other", which dropped them from punt training and would have excluded them from grading. ESPN live play-by-play uses the same labels. Both are now categorized, tested in `tests/test_plays.py`, and all models were retrained.

---

## Win probability

**Training data.** 1,692,153 pre-snap states from 10,694 games, downs 1–4, regulation only. Includes 1st-and-goal and 2nd/3rd down, so the game-page chart can plot every snap. Exclusions:
- invalid states;
- games failing D4;
- games with unknown timeouts;
- repeated no-play penalty states;
- games whose final score was tied.

The label is the official final result, including overtime.

**Model.** XGBoost with monotone constraints on the features where direction is unambiguous. The tuning protocol:
1. 30 seeded trials tune the tree structure.
2. The model is refit at learning rate 0.03, with rounds (443) chosen on validation.

**2024–25 holdout:**

| Slice | States | Log loss | Brier | Calibration error |
|---|---|---|---|---|
| All | 261,728 | 0.340 | 0.111 | 1.1% |
| 1st down | 105,412 | 0.338 | 0.110 | 1.1% |
| 2nd down | 78,093 | 0.340 | 0.111 | 1.2% |
| 3rd down | 50,142 | 0.343 | 0.112 | 1.3% |
| 4th down | 28,081 | 0.339 | 0.110 | 1.1% |
| 1st-and-goal inside the 10 | 5,965 | 0.319 | 0.103 | 2.0% |
| Q1 | 62,176 | 0.442 | 0.147 | 2.6% |
| Q4 | 66,115 | 0.222 | 0.071 | 1.2% |
| Q4, within 8 points | 23,392 | 0.508 | 0.171 | 2.9% |
| Final 2 minutes | 12,645 | 0.184 | 0.060 | 1.8% |

**Calibration** (predicted → observed, test): 0.03→0.02, 0.15→0.15, 0.25→0.27, **0.35→0.39**, **0.45→0.48**, 0.55→0.54, **0.65→0.61**, 0.75→0.74, 0.85→0.85, 0.97→0.98.

**Field-position sanity check against raw outcomes** (evenly matched, tied, first-half 1st-and-10):

| Field position | Observed win rate | Model |
|---|---|---|
| Own 1–20 | 49.9% | 50.8% |
| Own 21–40 | 52.6% | 52.8% |
| Midfield | 57.1% | 57.3% |
| Opponent 21–40 | 59.4% | 60.3% |
| Opponent 1–20 | 61.9% | 62.7% |

The model's modest value for field position matches the data. This is what drives the aggressive recommendations discussed in `docs/grades.md`.

**Design decisions, with the evidence behind each:**

1. **Two Elo ratings, not an Elo difference.**
   - For: an Elo difference improves Q1 calibration (2.0% vs 2.5% error).
   - Against: it loses log loss in every slice under both hyperparameter sets I tried, including the decision-relevant ones:

     | Test slice | Two Elos | Elo difference |
     |---|---|---|
     | Q4, within 8 points | 0.511 | 0.516–0.518 |
     | 4th down, 2nd half, within 8 | 0.545 | 0.550 |

   I tried the difference first and reverted.
2. **Explicit end-of-game indicators.** v1 had kneel-out indicators written and commented out; this version uses them.
   - The leader-can-kneel-out indicator fixes the leading-team end game. On training rows, a team leading by 1–3 with 30 seconds or less wins 98.9%; without the indicator the model predicted 87%.
   - Also added: "opponent could kneel out after a punt" and "trailing yards per second remaining".
3. **Learning-rate refinement.** Tuned configurations were indistinguishable on validation (0.3485–0.3489) but differed on test (0.3403–0.3412); the lower learning rate generalized better. **The 2024–25 test seasons were consulted for decisions 1 and 3, so the test numbers above are slightly optimistic.**

**Known limitations:**

- **Overconfident in the middle early in games.** In Q1–Q2, mid-range probabilities are 3–4 points too confident (0.35 predicted → 0.39 observed).
  - These did not fix it: temperature scaling, time-varying calibration, heavier regularization, row subsampling, removing Elo.
  - It varies by season (2023 was well calibrated), and early-game WP rests on only ~900 independent games per season.
- **WP too high for a team losing with the game almost over.**
  - Trailing offenses far from the goal with 30 seconds or less left: predicted ~5%, observed ~1%.
  - Teams trailing by 1–8 in the final two minutes: predicted 24.9% vs 29.3% observed (calibration error 5.7%).
  - See `future-improvements.md` Models #2.
- **Overtime isn't modeled.**
- **Not directly validated before 2024:** the clock reconstruction (D3, D12).

---

## Fourth-down conversion

**Feature ablation** (validation 2022–23, fourth downs, fixed hyperparameters):

| Feature set | Validation log loss |
|---|---|
| Situation + Elo (chosen: simplest within 0.001 of best) | 0.6307 |
| + weather | 0.6306 |
| + team form (D11) | 0.6306 |
| + team form + weather (closest to v1's inputs) | 0.6305 |
| Same, trained on 3rd **and** 4th downs | 0.6301 |
| Distance-only conversion rate | 0.6364 |

**Test (2024–25, by distance):**

| Distance | n | Predicted | Observed |
|---|---|---|---|
| 1 | 2,488 | 0.704 | 0.705 |
| 2–3 | 1,796 | 0.550 | 0.547 |
| 4–6 | 1,308 | 0.440 | 0.411 |
| 7–10 | 883 | 0.351 | 0.319 |
| 11+ | 458 | 0.190 | 0.212 |

**Selection check.** Fourth-down attempts are chosen by coaches, which could inflate conversion rates. At the same distance they convert like third downs, which are nearly unselected:

| Distance | 3rd down | 4th-down attempts |
|---|---|---|
| 1 | 74.0% | 70.3% |
| 4–5 | 44.8% | 44.6% |
| 8–10 | 29.8% | 32.6% |

The bias is small.

**Limitation:** 4–10 yard attempts ran about 3 points above observed in 2024–25. That feeds straight into go recommendations at those distances.

---

## Field goal

- **Scope:** 29,922 attempts from 76,123 fourth downs with yards to goal ≤ 50. Blocked kicks count as misses.
- **Heckman selection correction** (v1's design, refit as a diagnostic with v1's two defects fixed): the Mills-ratio coefficient came out at 0.010, and validation log loss was identical with and without it. The shipped model is therefore a **probit on attempts**, exported as JSON coefficients, with no statsmodels needed at inference. `pressure_rating` was dropped (coefficient −0.009).
- **Season trend** is linear, clamped to at most one season beyond training. Clamping to the last training season underpredicted every distance bucket in 2024–25; extrapolating was better (log loss 0.4899 vs 0.4907 in the variant comparison).

**Test (2024–25, by kick distance):**

| Kick distance | n | Predicted | Observed |
|---|---|---|---|
| <30 | 1,463 | 0.916 | 0.915 |
| 30–39 | 1,463 | 0.793 | 0.813 |
| 40–49 | 1,549 | 0.632 | 0.656 |
| 50–54 | 383 | 0.503 | 0.559 |
| 55+ | 74 | 0.436 | 0.527 |

**Limitation:** the model under-predicts 40+ yard makes in the newest seasons (kicking is improving faster than a linear trend). A season × distance interaction did not help (validation 0.49198 vs 0.49203). Revisit after 2026.

**No hard-coded probabilities.** v1 overwrote model output for 55+ yard kicks with fixed values (0.04 down to 0); that is gone. Feasibility (FG only within the model's 50-yard range) lives in the decision layer.

---

## Punt

- **Target:** the receiving team's yards to goal at its next snap, including touchbacks, returns and penalties on the return; 0 for a return TD. Built from 98,569 of 101,997 punts.
- **Features:** weather improved validation RMSE by only 0.016 yards (11.924 vs 11.940), so the model uses punt spot and the two Elos.

**Test (2024–25, by punt spot):**

| Punt yards to goal | n | Predicted mean | Observed mean | RMSE |
|---|---|---|---|---|
| <35 | 17 | 87.8 | 89.9 | 7.4 |
| 35–44 | 952 | 87.4 | 88.2 | 7.9 |
| 45–59 | 3,653 | 83.5 | 84.2 | 10.7 |
| 60–74 | 5,590 | 71.9 | 72.5 | 13.2 |
| 75+ | 3,990 | 56.9 | 57.7 | 13.7 |

- **Short punts.** Inside the 35 the receiving team starts at ~90 yards to goal; v1 hard-coded 80. Punts inside the 35 are rare (17 in two seasons), so that bucket is thin. The decision layer only offers a punt from 30+ yards to goal, the smallest spot with at least 50 training punts.
- **Residual quantiles** by punt spot are stored in `metadata.json`. The decision layer integrates WP over them instead of plugging in the mean.

---

## Decision assumptions (measured, for the grading layer)

| Quantity | v1 assumption | Measured, 2013–2025 |
|---|---|---|
| Opponent start after a made FG | own 20 (80 to goal) | median 75, mean 74.1 |
| Opponent start after an offensive TD | own 20 | median 75, mean 73.7 |
| Yards past the line to gain on a non-TD conversion | 0 | mean 5.6, median 3; full distribution by field zone and distance |
| Opponent start after a failed attempt, relative to line of scrimmage | 0 | median 0, mean −0.4 |
| Opponent start after a missed/blocked FG, relative to line of scrimmage | 0 | median 0, mean −2.8 |
| Clock to the next snap after a conversion | 5 s | 28.6 s (14 s in the final two minutes of a half) |
| Clock to the next snap after a turnover on downs / TD / made FG / missed FG / punt | 5 s | 9 / 9 / 7.2 / 6.2 / 8 s |

The artifact also holds weather defaults for missing forecasts, and the timeout lookup used when a game never recorded timeouts.

---

## What live inference now needs

This updates `v1-audit.md` §3.6. Every shipped input is one of the following:
- live from ESPN: score, clock, down, distance, field position, home/neutral;
- timeouts, counted from ESPN summary timeout plays, because scoreboard timeout counts don't reset at halftime (see `docs/grades.md`);
- a pregame snapshot (`jobs.pregame_snapshot`): closing spread, both teams' Elo ratings;
- static: elevation, indoors;
- a CFBD pre-game weather forecast (FG model only).

**No model needs CFBD PPA or CFBD advanced stats.** In the 2026-09-13 replay, ESPN populated `possession` on every pending fourth down. Offense, field position, distance and score matched the subsequent play 100% of the time (17 of 17). Timeouts are the weakest live input.

---

## Conflicts with the written plan (flagged, not changed)

Per `CLAUDE.md`, these are flagged rather than silently edited into the specs. More grading-specific conflicts are in `docs/grades.md`.

1. **`docs/data-pipeline.md` Stage 3 model descriptions** don't match what was built.
   - WP inputs include spread, Elo and end-of-game indicators.
   - Conversion is situation + Elo, not "optionally adjusted".
   - FG is a probit on distance, weather, elevation and a season trend.
   - The punt model yields a mean plus residual quantiles that the decision layer integrates over.

   *Change the doc.*
2. **Raw cache layout.** The spec says `data/raw/{season}/{week}/{game_id}.json`. Built:
   - `data/raw/cfbd/{endpoint}/{params}.json.gz`, write-once, for settled seasons;
   - `data/raw/cfbd_snapshots/…` and `data/raw/espn/…`, as timestamped immutable snapshots for data that changes.

   *Change the doc.*
3. **CFBD budget.** `data-pipeline.md` says "~200/hour" and `automation.md` says "fits in free tiers".
   - Measured: a full 13-season rebuild costs 318 calls; each pregame snapshot run costs 6.
   - Free tier: 1,000 calls/month.
   - Tier 1: 5,000 calls/month; it includes weather, which the FG model uses.

   *Change both docs.*
4. **Week keys in `docs/api-contract.md`.** CFBD and ESPN number weeks differently (CFBD 2026 week 2 = ESPN week 3). Routes keyed by `season/week` need a declared week source plus `season_type`. *Change the contract.*
5. **`wp_series`** (audit C8) is now feasible for every snap; no contract change needed.
6. **Overtime** is excluded from WP training and from grading. The plan never mentions overtime. *Add to data-pipeline exclusions and to Methodology.*
7. **Replay.** Replaying a run needs the model artifacts **and** `artifacts/data_build/` and `artifacts/decision_assumptions/`. Model versioning must cover all three. *Change the doc.*

## Status

Grading, the 2013–2025 backfill, the v1 comparison, the pregame snapshot job and live inference are built and documented in `docs/grades.md`. Everything deferred is in `docs/future-improvements.md`.

**Nothing is committed.** These are gitignored:
- raw data (105 MB, including tonight's ESPN capture);
- processed data (104 MB);
- the SQLite database (96 MB, too large for git; rebuild it with `jobs.backfill` or publish it separately).

Model artifacts (3.2 MB) are small enough to commit if you want them in git.
