# Grades v2.0.0: decision layer, backfill, v1 comparison, live inference

Built 2026-09-12/13, on top of the retrained models in `docs/models.md`. Grades are **model output, not ground truth**. The section "Read this before trusting the numbers" says where they're weakest.

## What exists

| Piece | Where | Run |
|---|---|---|
| Option evaluator (go / FG / punt expected WP) | `backend/modeling/options.py` | library |
| Thresholds, recommendation, verdict | `backend/app/grading.py` | library |
| Shared batch/live pipeline | `backend/app/decisions.py` | library |
| SQLite store | `backend/app/db.py` → `backend/data/cfb4thdown.db` | created on first connect |
| Historical grades | `backend/jobs/backfill.py` | `uv run python -m jobs.backfill --from 2013 --to 2025` (~20 s) |
| Pregame snapshots | `backend/jobs/pregame_snapshot.py` | `uv run python -m jobs.pregame_snapshot --season 2026` (6 CFBD calls) |
| Live inference | `backend/jobs/live_poll.py` | `--once`, `--loop`, or `--replay` (from captured raw data) |
| Live capture (raw only) | `backend/jobs/live_capture.py` | `--minutes 180` |
| ESPN provider | `backend/providers/espn.py`, `providers/rawstore.py` | library |
| v1 comparison | `backend/analysis/compare_v1.py` → `modeling/reports/v1_vs_v2.json` | `uv run python -m analysis.compare_v1` |
| Live parsing validation | `backend/analysis/validate_live.py` → `modeling/reports/live_validation.json` | `uv run python -m analysis.validate_live` |

**Tables:** `games`, `plays_fourth_down`, `exclusions`, `pregame_snapshots`, `live_pending`, `live_decisions`, `run_log`.

**Tests:** 37 pass (`uv run pytest`), with obviously fake fixtures per `CLAUDE.md`. They cover:
- grading thresholds;
- option feasibility and end-of-game resolution;
- ESPN field position, possession fallback, pre-snap scores, snap clock and timeout counting;
- the Elo leak guards;
- stale-clock interpolation.

---

## How a fourth down is graded

For a pre-snap state (score, clock, field position, down/distance, timeouts, pregame spread and Elo, kick context):

```
wp_go         = P(convert) · E[WP | converted] + (1 − P(convert)) · WP(opponent ball at the spot)
wp_field_goal = P(make) · WP(+3, opponent after kickoff) + (1 − P(make)) · WP(opponent at spot, or its 20)
wp_punt       = E[WP(opponent ball at punt result)]
recommendation = best feasible option; margin = best − next best
wp_delta      = WP(what the coach did) − WP(recommendation)   (0 when they matched)
```

**Every assumption is measured** (`artifacts/decision_assumptions/2.0.0/assumptions.json`), not hand-picked:

- **Converted attempts:** yards past the line to gain come from a 10-point empirical distribution, by field zone and distance. Gains that reach the goal line are touchdowns (+7; 91% of CFBD touchdown rows move the score by exactly 7).
- **Opponent start after a score:** median own 25. v1 assumed the 20.
- **Missed field goal:** opponent at the line of scrimmage, or its 20 if the kick was from inside the 20 (NCAA rule; 98.4% of misses in the data).
- **Punt result:** the punt model's mean plus seven residual quantiles, integrated with quantile weights. v1 plugged in the mean.
- **Clock runoff to the next snap,** measured per transition, with a separate median for the final two minutes of a half:

  | Transition | Median seconds | Final 2 min |
  |---|---|---|
  | Conversion, same offense | 28.6 | 14 |
  | Turnover on downs | 9 | 7 |
  | Touchdown then kickoff | 9 | 7 |
  | Made FG then kickoff | 7.2 | 5 |
  | Missed FG | 6.2 | 3.5 |
  | Punt | 8 | 7 |

- **End of regulation:** if the clock expires in Q4, the outcome is resolved by the score. **Overtime is not modeled**: a tie at the end of regulation is scored 50/50.

**Feasibility.** Infeasible options are `null` and never recommended:
- field goal only from ≤ 50 yards to goal, the FG model's training range;
- punt only from ≥ 30 yards to goal, the smallest spot with ≥ 50 training punts.

**Verdicts and confidence** live in `app/grading.py` only:
- `mistake`: |wp_delta| ≥ 0.05.
- `marginal`: didn't match, but below that threshold.
- `correct`: matched.
- Confidence: `clear` (margin ≥ 0.05), `close` (0.02–0.05), `toss_up` (< 0.02), `only_option`.

**Exclusions.** Every excluded fourth down is stored with its reason. Totals for 2013–2025:

| Reason | Plays |
|---|---|
| Penalty with no play (decision unknowable) | 10,266 |
| Garbage time: pre-snap WP outside 1–99% with < 5 min left | 8,674 |
| Game failed the play-by-play score gate (`models.md` D4) | 7,133 |
| Invalid state | 626 |
| Overtime | 579 |
| Punt from inside the 30 | 44 |
| Kneel or spike | 29 |
| Field goal from beyond 50 yards to goal | 20 |
| Unclassifiable play | 17 |

Timeouts were imputed from measured medians (by half and minute) for 453 graded plays in games that never recorded them. They are flagged in `timeouts_imputed`.

---

## Backfill: 2013–2025

**160,357 fourth downs graded** in 10,724 games (148,709 by FBS offenses). Figures below are FBS offenses only.

| Season | Graded | Model says go | Coaches went | Mistakes (≥ 5% WP) | WP lost per game (both teams) |
|---|---|---|---|---|---|
| 2013 | 10,756 | 59.9% | 17.5% | 1.57% | −0.083 |
| 2014 | 12,107 | 59.3% | 17.5% | 1.60% | −0.087 |
| 2015 | 12,268 | 58.7% | 17.8% | 1.65% | −0.083 |
| 2016 | 11,957 | 58.3% | 18.7% | 1.46% | −0.077 |
| 2017 | 12,313 | 58.7% | 18.0% | 1.53% | −0.084 |
| 2018 | 12,036 | 57.9% | 20.2% | 1.21% | −0.073 |
| 2019 | 12,054 | 57.3% | 19.7% | 1.29% | −0.069 |
| 2020 | 7,755 | 58.1% | 22.5% | 0.76% | −0.067 |
| 2021 | 10,912 | 56.3% | 22.6% | 1.15% | −0.067 |
| 2022 | 11,586 | 56.7% | 23.3% | 1.00% | −0.069 |
| 2023 | 11,759 | 57.2% | 22.7% | 1.17% | −0.065 |
| 2024 | 11,605 | 57.0% | 24.0% | 1.15% | −0.065 |
| 2025 | 11,601 | 57.1% | 25.8% | 1.09% | −0.060 |

**Headline findings:**
- **Recommendations vs. what coaches do.**
  - When the model recommends a punt, coaches punt 95.5% of the time.
  - When it recommends a field goal, they kick 74.6%.
  - When it recommends going for it, they go only 30.8%.
- **Coaches are moving the model's way.** The go rate rose from 17.5% to 25.8% over 2013–2025, and WP lost per game fell by about a quarter.
- **Most calls are close.**
  - 76% of decisions have a margin under 2 points (`toss_up`); 5% are `clear`.
  - Only 1.3% of decisions lose ≥ 5 points of WP.
  - The mean wp_delta on non-matching calls is −0.012.

### Read this before trusting the numbers

1. **The model is much more aggressive than coaches, and than conventional wisdom.** It recommends going for it on 58% of fourth downs, including:
   - 94% of 4th-and-1s;
   - 54% of 4th-and-7-to-10s;
   - a toss-up on 4th & 10 from your own 20, tied in Q2.

   I checked the WP model's field-position slope against raw outcomes. For evenly matched (|spread| ≤ 3), tied, first-half 1st-and-10 states, the actual win rate is 49.9% at own 1–20, 52.6% at own 21–40, 57.1% at midfield and 61.9% at opponent 1–20. The model gives 50.8 / 52.8 / 57.3 / 62.7%. So the small value of field position is what the data says, not a model bug. College games have enough possessions and variance that one possession's field position moves WP less than intuition expects.

   Still, the rankings and headline numbers will be read as strong claims. **Have someone with football-analytics judgment review a sample of `clear` go recommendations before these grades drive the Punt Index.**
2. **Backfill grades are in-sample.** Seasons 2013–2025 are graded by models trained on those seasons. A leave-one-season-out regrade is in `future-improvements.md`.
3. **Clocks before 2024 are partly reconstructed.** 29% of graded plays use an interpolated clock (`clock_source`); simulated error is about 10 s.
4. **Overtime is ungraded.** End-of-regulation ties are scored 50/50.
5. **Win probability is too high for a team losing with the game nearly over.** This inflates the value of giving the ball back late (`models.md`, `future-improvements.md` Models #2).

### Textbook situations (final models)

Even teams, neutral site, 7 mph wind:

| Situation | P(convert) | WP go | WP FG | WP punt | Recommendation |
|---|---|---|---|---|---|
| 4th & 1, own 30, Q2 tied | 0.73 | 0.519 | — | 0.444 | go (clear) |
| 4th & 5, own 30, Q2 tied | 0.47 | 0.478 | — | 0.444 | go (close) |
| 4th & 10, own 20, Q2 tied | 0.32 | 0.430 | — | 0.426 | go (toss-up) ⚑ |
| 4th & 2, opp 38, Q2 tied | 0.58 | 0.539 | 0.511 | 0.471 | go (close) |
| 4th & 8, opp 35, Q2 tied | 0.37 | 0.513 | 0.524 | 0.471 | field goal (toss-up) |
| 4th & goal at 3, Q2 tied | 0.49 | 0.595 | 0.597 | — | field goal (toss-up) |
| 4th & 6, opp 20, Q2 tied | 0.39 | 0.543 | 0.572 | — | field goal (close) |
| 4th & 3, opp 45, 2:00 Q4, down 4 | 0.52 | 0.284 | 0.191 | 0.192 | go (clear) |
| 4th & 10, own 40, 1:00 Q4, up 3 | 0.34 | 0.701 | — | 0.777 | punt (clear) |
| 4th & 4, opp 30, 0:10 Q4, down 2 | 0.48 | 0.065 | 0.512 | 0.052 | field goal (clear) |

---

## v2 vs. v1's published grades

`analysis/compare_v1.py` joins v1's `results/*.parquet` (read-only) to v2 on CFBD play ID, restricted to FBS offenses, which is v1's scope.

**Coverage**
- v1 rows: 162,874. v2 graded FBS-offense rows: 148,709. Graded by both: 146,688.
- **In v1 but not v2 (16,186):**

  | Reason in v2 | Plays |
  |---|---|
  | Garbage time | 7,617 |
  | Game failed the score gate | 6,066 |
  | No-play penalty (v1 graded these) | 1,908 |
  | Invalid state | 454 |
  | Other | 141 |

- **In v2 but not v1:** 2,021, mostly plays v1's text rules left unclassified.
- **The two versions agree on what the coach did 99.99% of the time.**

**Recommendations**
- They agree on **66.2%** of plays, steady at 65–67% in every season.
- v2 recommends going for it far more often:

  | Distance | v1 go rate | v2 go rate |
  |---|---|---|
  | 1 | 79% | 94% |
  | 2–3 | 64% | 86% |
  | 4–6 | 50% | 70% |
  | 7–10 | 36% | 54% |
  | 11+ | 16% | 15% |
  | **Overall** | **43.5%** | **57.8%** |

- v2 is *less* aggressive than v1 inside its own 20 (28% vs 40%). There v1's plug-in punt value and 80-yard touchback assumption made punting look worse.
- **Confusion matrix** (v1 rows, v2 columns):

  | v1 \ v2 | go | field goal | punt |
  |---|---|---|---|
  | go | 50,976 | 15,121 | 18,667 |
  | field goal | 4,080 | 12,871 | 1,335 |
  | punt | 8,783 | 1,542 | 33,313 |

**Option win probabilities** are highly correlated but shifted:

| Option | Correlation | Mean abs difference | Mean v2 − v1 |
|---|---|---|---|
| Go | 0.988 | 3.1 pts | −0.5 |
| Field goal | 0.980 | 4.4 pts | −1.7 |
| Punt | 0.992 | 2.7 pts | −0.1 |

**Verdicts (same 5% threshold)**

| | Correct | Marginal | Mistake |
|---|---|---|---|
| v1 | 61.2% | 37.9% | 0.9% |
| v2 | 55.3% | 43.4% | 1.3% |

**Rankings change a lot.** Team-season WP-lost rank correlation between v1 and v2 is 0.43–0.68 per season (2025: 0.45). The largest 2025 moves:
- Iowa: rank 99 → 11 of 136 by WP lost;
- Northern Illinois: 97 → 12;
- Hawai'i: 109 → 22;
- UCLA: 43 → 135;
- BYU: 20 → 107.

**Any Punt Index built on v1 numbers should not be carried forward.**

**The largest disagreements are v1's score leak** (audit B1). All top 10 are walk-off field goals in the last 5 seconds: UCLA–South Alabama 2022, Iowa State–Texas 2019, BYU–Utah 2024, and others. v1 scored go, FG and punt all at 1.000, because the made kick's 3 points were already in its pre-snap score. v2 scores the kick at 0.69–0.94 and going for it at 0.04–0.27.

**v1's to-do anomaly** ("2025 Vanderbilt vs Missouri 4th & 4 at 93 yards to go, recommending go with 7.8% WP gain over punt"):
- v1's stored values: go 0.474 / punt 0.439.
- v2: go 0.498 / punt 0.470, conversion 46%. v2 still says go, but it's a `close` call (2.8-point margin), not a large edge.
- The real play was a punt.

---

## Live inference

### Pregame snapshots

`jobs.pregame_snapshot` fetches fresh CFBD games, lines and weather for the season (6 calls), writing timestamped raw snapshots. For each target game it stores:
- Elo replayed through every final game that kicked off before it. This matches training Elo exactly: 0.0 difference on 120 random games.
- Median closing spread, or the Elo-imputed spread if there's no market.
- CFBD weather (a forecast before kickoff), indoors, and elevation.

On 2026-09-13 it snapshotted all 80 games that kicked off that day: 0 imputed spreads and 0 default-weather games. Live inference never calls CFBD.

### Live poll

`jobs.live_poll`:
1. Fetches the FBS scoreboard plus a summary for each live game, all written to `data/raw/espn/` before parsing.
2. Writes `live_pending`, the recommendation *before* the snap for games sitting on fourth down.
3. Writes `live_decisions`, fourth downs already in ESPN's play-by-play, graded through the same pipeline as the backfill.

### Tonight's test

The capture recorded the 2026-09-13 00:00–06:00 UTC slate (15 live FBS games at start). Replaying it from disk:
- 49 scoreboards processed;
- 62 pending-decision states evaluated;
- 124 completed fourth downs graded across 12 games: 64 correct, 60 marginal, 0 mistakes.

**Pending-state validation** (`analysis/validate_live.py`). Each pending state was matched to the fourth-down play that followed it in ESPN's play-by-play, for 17 pending states:

| Field | Agreement |
|---|---|
| Offense | 100% |
| Yards to goal | 100% |
| Distance | 100% |
| Score | 100% |
| Offense timeouts | 53% |
| Defense timeouts | 77% |

Other findings from the validation:
- **Possession** was present in the scoreboard for every pending fourth down, so the null-possession fallback wasn't needed tonight.
- **Timing:** the pending clock was a median 4 s ahead of the snap (up to 42 s), so the card has a window.
- **10 scoreboard states** showed `down = 4` with `yardLine = 0` and no down/distance text between plays. They were rejected as invalid, which is correct.
- **12 pending states** had no matching play in the latest captured play-by-play at validation time.

**Timeouts are the weakest live input.**
- ESPN's scoreboard timeout counts don't appear to reset at halftime. Second-half scoreboard values implied 4.7 timeouts used per poll, versus 0.7 counted from the play-by-play.
- The live path therefore counts timeout plays in the summary (calling team = the participant flagged `"timeout": true`).
- Remaining disagreement mixes genuine timeouts called between detection and snap with summaries that lag the scoreboard.
- Not independently verified. CFBD derives from ESPN, so it's not an independent check either.

**Live and batch grades are not reconciled yet.** ESPN play IDs (e.g. `401856672715`) differ from CFBD play IDs for the same play. When CFBD publishes 2026 week 2, those plays will be graded by `jobs.backfill`, but nothing links them to `live_decisions` rows.

---

## Conflicts with the written plan (flagged, not changed)

1. **`docs/data-pipeline.md` Validation: "Fourth downs per game should fall between 2 and 20."**
   - Counting both offenses, the median is 15 graded fourth downs per game, and 753 of 10,724 games (7%) exceed 20.
   - The backfill implements the check as written, so it flags 23–85 games per season.
   - *Change the doc* to per-team counts or a 2–30 band.
2. **`docs/api-contract.md` Decision object.**
   - `wp_field_goal` and `wp_punt` must be nullable (infeasible options).
   - `confidence` needs `only_option`.
   - A `source` (`cfbd` | `espn`) and `clock_source`/`timeouts_imputed` quality flags exist and should be exposed.
   - The contract's `id` format (`401628201-0142`) matches neither CFBD nor ESPN play IDs.

   *Change the contract.*
3. **`docs/automation.md` live-poll cost.** A useful live poll needs one ESPN summary per live game per poll (possession fallback, timeouts, play-by-play). That's 16 requests per poll with 15 live games; at 20 s that's about 48 requests a minute to an undocumented API. *Add to the doc*, and consider fetching summaries only for games on or near fourth down.
4. **`docs/data-pipeline.md` Stage 2 garbage time** is implemented exactly as written (WP outside 1–99%, < 5 min). It removes 8,674 fourth downs, more than any other reason except no-play penalties. Confirm this is intended.
