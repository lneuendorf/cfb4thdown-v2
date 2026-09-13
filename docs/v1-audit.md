# v1 audit: can the v1 models be reused?

Audit date: 2026-09-12 (live ESPN capture taken 2026-09-13 00:41–00:46 UTC, during the week 3 Saturday slate).
Scope: `../4th-down-models`, `../4th-down-pipeline`, `../cfb-4th-down-app` (all read-only), against `CLAUDE.md`, `README.md` and `docs/`.

**Evidence labels used below**

- **[verified]**: I ran code or queried data to confirm it. The scripts lived in a scratch directory and are not committed.
- **[code]**: read directly from source; not executed.
- **[uncertain]**: inference or unverified documentation. Treat as a hypothesis.

---

## 0. Summary

1. **The artifacts load and reproduce v1 exactly.** Running the v1 pipeline's inference modules on 25,822 graded 2024–25 fourth downs, with the saved model files, reproduced every stored `exp_wp_go/fg/punt` and `fg_make_proba` to a max absolute difference of 0.000000 **[verified]**. The notebooks are not needed at inference time.
2. **v1's graded outputs contain a data leak that changes recommendations.**
   - **The leak:** CFBD's `offense_score` and `defense_score` on a play row are the score *after* that play **[verified]**: 98% of `Field Goal Good` rows already include the +3. v1 uses those scores as the pre-decision state.
   - **Effect on recommendations:** correcting the scores flips the recommendation on **26.6% of plays that scored** (4.65% of all 2024–25 fourth downs), and moves each option's WP by about 0.07 on average **[verified]**.
   - **Effect on training:** the same leak is baked into the WP, conversion and FG-selection training data. That part can't be fixed without retraining.
3. **v1 has other train/serve mismatches and bugs.** Details are in §2.6. The ones that matter most:
   - **FG model:** the inverse Mills ratio is computed from a probability instead of the linear index (0.6% of recommendations flip).
   - **Elo:** postseason games get *preseason* Elo, and every season's bowl results leak into that season's regular-season Elo from week 2 onward.
   - **Win-probability model:** it was trained only on 1st-and-10 and 4th-down snaps. It is then evaluated on 1st-and-goal states it never saw.
4. **Live inference is mechanically possible; the current models aren't good enough to put in front of users.**
   - **What works:** nothing the models consume needs post-game data. Every season-aggregate feature is built only from earlier weeks **[code]**, so it can be precomputed before kickoff. ESPN's live JSON provides or lets us derive every in-game input **[verified]**.
   - **Weather:** wind speed and precipitation (in the units the models were trained on) are not available live.
   - **The real blocker:** the models need retraining anyway (point 2), and a live grade from pre-snap state would disagree with v1's post-game batch grade on every scoring play.
5. **Verdict: retrain, using the v1 notebooks as the recipe.** The punt model is the exception and can be reused with small changes. **Cut live grading (the pending-decision card and live WP deltas) from the first data phase.** A live score ticker from ESPN is fine to keep. Details in §5.

---

## 1. Model inventory

v1 is not "four models". Grading a single fourth down uses **six fitted artifacts** (win probability, conversion, FG selection, FG outcome, and the two punt models), **five fitted auxiliary regressions**, **two in-house derived ratings**, and **several hard-coded rules**.

### 1.1 Overview

| # | Model | Predicts | Algorithm | Artifact | Trained on | Loads without notebook |
|---|---|---|---|---|---|---|
| 1 | Win probability | P(offense wins) | XGBoost `binary:logistic`, 210 trees, monotone constraints | `models/win_probability/xgb_classifier.json` | 2013–2025, FBS offense, regulation, **only `down==1 & distance==10` or `down==4`** | Yes **[verified]** |
| 2 | Fourth-down conversion | P(gain ≥ distance, no INT, no sack) | XGBoost `binary:logistic`, 38 trees | `models/fourth_down/xgb_classifier.json` | 35,761 FBS 4th-down run/pass plays, 2013–2025, penalties removed, one play per drive in train | Yes **[verified]** |
| 3a | FG selection (Heckman stage 1) | P(team attempts FG) | statsmodels Probit, standardized inputs | `models/fg_probability/selection_model.pkl` + `scaler_selection.pkl` | 70,434 FBS 4th downs (kick ≤ 65 yds) | Yes, with statsmodels 0.14.x **[verified]** |
| 3b | FG outcome (Heckman stage 2) | P(make \| attempt) | statsmodels Probit + inverse Mills ratio | `models/fg_probability/outcome_model.pkl` + `scaler_outcome.pkl` | 29,952 FBS attempts | Yes, with statsmodels 0.14.x **[verified]** |
| 4a | Punt result (XGB) | Receiving team's yards-to-goal at next drive start | XGBoost `reg:absoluteerror` (median), 62 trees | `models/punt_yards_to_goal/xgb_classifier.json` | 44,238 punts from ≥ 40 yards to goal (see §1.5 on FBS filter) | Yes **[verified]** |
| 4b | Punt result (OLS) | Same, mean | statsmodels OLS | `models/punt_yards_to_goal/linear_regression_model.pkl` | Same | Yes **[verified]** |

Auxiliary fitted artifacts, all of which feed the models above:

| Artifact | What | Where | Provenance |
|---|---|---|---|
| `offense_success_rate_model/offense_pass_success_regression_coefficients.json` | Prior: pass success rate = 0.310924 + 5.2457e-05 · Elo | models repo | Fit in `04_fourth_down_model.ipynb` cell 10 |
| `offense_success_rate_model/offense_rush_success_regression_coefficients.json` | Prior: rush success rate = 0.342620 + 4.4455e-05 · Elo | models repo | Same |
| `point_spread_imputation/regressor.pkl` | sklearn LinearRegression: home_spread = −6.358 − 0.02005 · home_elo + 0.02145 · away_elo | **pipeline repo only**, 2026-01-09 | **Unknown.** The WP notebook refits this in memory (cell 14) and never saves it |
| `team_strength/offense.pkl`, `defense.pkl` | sklearn LinearRegression: strength = a + b · Elo (offense 0.000148, −0.2696; defense 0.000148, −0.2479) | **pipeline repo only**, 2026-01-09 | **Unknown.** The conversion notebook refits in memory (cell 31) and never saves it |

Derived ratings with no saved artifact (recomputed by code):

- **Elo:** in-house (`elo_updater.py`, `01_elo.ipynb`). K=100, home-field 100, divisor 800, margin-of-victory multiplier `log(|MOV|+1)/2`. Initial ratings: FBS 1500, FCS 1300, D-II 1000, D-III 800. No regression to the mean between seasons. Replayed from 1930.
- **Team offensive/defensive strength:** SLSQP least-squares fit of CFBD per-game offensive PPA (garbage time excluded) over the last 10 distinct (season, season_type, week) slices before the target week. Strengths are bounded to [−1, 1] with mean zero.

### 1.2 Win probability, exact inputs

Feature order as stored in the booster **[verified]**. "Units" describes the values the pipeline feeds in.

| Feature | Type in booster | Units / definition |
|---|---|---|
| `score_diff` | int | `offense_score − defense_score` (post-play scores, see §2.2) |
| `offense_score` | int | points, clipped ≥ 0 |
| `defense_score` | int | points, clipped ≥ 0 |
| `diff_time_ratio` | float | `score_diff · exp(4 · pct_game_played)` |
| `spread_time_ratio` | float | `pregame_spread · exp(−4 · pct_game_played)` |
| `pregame_offense_elo` | float | in-house Elo |
| `pregame_defense_elo` | float | in-house Elo |
| `pct_game_played` | float | `1 − game_seconds_remaining/3600` |
| `seconds_left_in_half` | int | `(2−period)·900 + clock` for periods 1–2, `(4−period)·900 + clock` for 3–4 |
| `is_home_team` | int | 1 offense home, −1 offense away, 0 neutral site |
| `offense_timeouts` | float | 0–3 (NaN allowed in training) |
| `defense_timeouts` | float | 0–3 |
| `yards_to_goal` | int | offense perspective, 0–100 |
| `down` | int | 1–4 |
| `distance` | int | yards to first down, capped at `yards_to_goal` |
| `seconds_after_kneelout` | int | Deterministic simulation: seconds left if the offense kneels out. 40-second play clock, 2-second kneel, two-minute warning, defensive timeouts |
| `seconds_after_punt_and_opponent_kneelout` | int | Same, after a 7-second punt, an opponent kneel-out, and a punt back |

- **Label:** `won = final score margin > 0` from the offense's perspective. The final score includes overtime.
- **Split:** random by `game_id`, 80/20 test, then 80/20 train/validation. It is not a temporal split, so historical (backfill) grades are effectively in-sample.
- **Metrics:** log loss train 0.341 / validation 0.354 / test 0.374. Brier 0.1117, computed over all rows including training rows.
- **Tuning:** 50 Optuna trials with an unseeded sampler, so a re-run will not reproduce the artifact.

**Ambiguity worth quoting.** WP notebook, cell 12:

```python
.query('(down == 1 and distance == 10) or down==4') # for a 4th down model, only 1st and 10 or 4th downs
```

The pipeline then evaluates this model on post-conversion states built as `down=1, distance=min(10, yards_to_goal − distance)`. That is **1st-and-goal from inside the 10, a state that has zero rows in training.** Every "go" recommendation near the goal line depends on extrapolation. It also means the model cannot legitimately produce a full-game WP line: 2nd and 3rd downs were never in training.

### 1.3 Fourth-down conversion, exact inputs

| Feature | Type | Units / definition |
|---|---|---|
| `distance` | int | yards, capped at `yards_to_goal` |
| `diff_time_ratio` | float | as above |
| `is_home_team` | int | 1 / −1 / 0 |
| `precipitation` | float | CFBD weather. Presumably inches; max observed 1.059. 0 if indoors. **[uncertain on unit]** |
| `wind_speed` | float | CFBD weather, mph (0–40 observed); 0 if indoors. **Not used by any split in the saved booster** (absent from gain importance) |
| `temperature` | float | CFBD weather, °F (−28.1 to 107.1 observed; the −28 looks like bad data); 70 if indoors |
| `yards_to_goal` | int | offense perspective |
| `offense_pass_success_adjusted` | float | see §2.3 |
| `offense_rush_success_adjusted` | float | see §2.3 |
| `offense_strength` | float | PPA-based strength, see §1.1 |
| `defense_strength` | float | PPA-based strength |

- **Label:** `yards_gained >= distance and not interception and not sack`.
- **Metrics:** test log loss 0.632, Brier 0.2192.
- **Tuning:** unseeded Optuna.

### 1.4 Field goal (Heckman two-stage), exact inputs

- **Selection probit:** continuous inputs `yards_to_goal, score_diff, pct_game_played, pregame_offense_elo, pregame_defense_elo, distance, wind_speed, temperature, elevation` go through `scaler_selection`. Binary inputs are `is_home_team, grass, game_indoors`, plus a constant.
- **Outcome probit:** inputs are `season, yards_to_goal, pregame_offense_elo, pressure_rating, wind_speed, elevation` through `scaler_outcome`, plus `lambda` (inverse Mills ratio, unscaled) and a constant.
  - Coefficients: `yards_to_goal` −0.670, `lambda` −0.131, `pressure_rating` −0.110, `season` +0.074.
- **Kick distance:** assumed to be `yards_to_goal + 17`.
- **Elevation:** CFBD venue elevation, stored as a string; meters.
- **`pressure_rating`:** a hand-built score from 0 to 4 based on clock and score state.
- **`season` is a linear feature:** 2026 is extrapolated past the 2013–2025 training range.

**Scaler quirk [verified].** `scaler_outcome.pkl` has mean 0 and scale 1 for `yards_to_goal`, `pregame_offense_elo`, `wind_speed`, `elevation`. The notebook standardizes those columns in place with the selection scaler (cell 24), then fits the outcome scaler on the already-standardized columns (cell 34). The pipeline also transforms in place, so train and serve currently agree by accident. Any reimplementation that applies each scaler to raw inputs will silently break the FG model.

### 1.5 Punt, exact inputs

- **XGB inputs:** `punt_team_end_yards_to_goal, elevation, wind_speed, precipitation, temperature, punting_team_pregame_elo, receiving_team_pregame_elo`.
- **OLS inputs:** `punt_team_end_yards_to_goal, elevation, temperature, punting_team_pregame_elo, receiving_team_pregame_elo` plus a constant.
- **Output:** the average of the two, giving the receiving team's yards to goal. Touchdowns count as 0, safeties as 100.
- **Short punts:** below 40 yards to goal the pipeline skips both models and uses a constant 80 (a touchback).
- **No score features.** Unlike the other models, the punt model is not affected by the post-play score leak.

**Ambiguity worth quoting.** Punt notebook, cell 24:

```python
# Only FBS offense
df = df.query('offense_division == "fbs"').reset_index(drop=True)
print(f'After filtering to FBS offense, {df.shape[0]} plays remain.')
```

The model is fit on `df_punts` (cells 26–31), not `df`, so this filter does not appear to apply to the training data. I can't tell whether the model was meant to be FBS-only. The training frame `df_punts` was built before this cell.

### 1.6 Serialization and portability

| Format | Files | Portability notes |
|---|---|---|
| XGBoost JSON (saved by 2.1.1) | WP, conversion, punt XGB | Portable across XGBoost versions and languages. Feature names are embedded **[verified]** |
| statsmodels pickle | FG selection, FG outcome, punt OLS | Tied to statsmodels/pandas pickle compatibility; loaded under statsmodels 0.14.6 and pandas 2.3.3. They are plain linear models, so **export their coefficients to JSON** in v2 rather than depend on pickles |
| sklearn pickle (1.5.2) | two scalers, spread regressor, two strength regressors | Same; export mean/scale and coefficients |
| JSON coefficients | success-rate priors | Portable |

Environment used for verification: conda env `4thdown` with xgboost 2.1.1, statsmodels 0.14.6, scikit-learn 1.5.2, pandas 2.3.3, numpy 1.26.4. **`env.yml` pins only numpy and scikit-learn**, so a fresh environment is not guaranteed to load the statsmodels pickles.

**Repo coupling [verified].** Every model file in `4th-down-pipeline/models/` except the three `point_spread_imputation`/`team_strength` pickles is a **git-committed symlink to an absolute path** (`/Users/lukeneuendorf/projects/cfb-4thdown/4th-down-models/...`). `4th-down-pipeline/data` is an untracked absolute symlink to the models repo's data directory. The pipeline runs on exactly one machine.

**Filename mismatch [verified].** The notebook saves `scaler_*.pkl`, the pipeline opens `scalar_*.pkl`, and a symlink with the misspelled name bridges them.

### 1.7 Version skew between notebooks and artifacts

| Artifact | Artifact commit | Notebook state | Skew? |
|---|---|---|---|
| WP | 2026-03-28 (`6b21f7b`) | Notebook outputs dated 2026-03-28 14:42; `best_score` in artifact 0.35390 matches notebook's final validation log loss 0.354 | Consistent |
| Conversion | 2026-04-18 (`656d570`) | Working tree has **uncommitted** edits; the code diff is only a plotting cell (`dist = 2` → `1`) **[verified]** | Consistent (cosmetic) |
| FG | 2026-03-28 (`6b21f7b`) | Notebook summary coefficients match the pickled params exactly **[verified]** | Consistent |
| **Punt** | **2026-01-24 (`b1dc5f9`)** | Displayed notebook run is dated **2026-03-05**; saved OLS `const` = 116.1579 vs displayed 116.1983; execution counts show save cells (exec 36–37) from a different kernel session than training cells (exec 49–52) **[verified]** | **Artifact is not the run shown in the notebook.** Feature code is unchanged between the two commits apart from cosmetics, so the input contract is the same. The tuned hyperparameters are not recoverable |
| Punt constant below 40 yards to goal | n/a | Notebook cell 40: "median yards to goal is 89", sets 89 | **Pipeline uses 80** (commit `19d48ae`, touchback assumption) |
| Spread and strength imputation pickles | pipeline repo, 2026-01-09 | Notebooks refit these in memory and never save them | **No provenance** |
| Offense success-rate blend | pipeline `cb03424` (2026-04-18, "did not match how the feature was created for training") | Training uses `max_week = 16` for all seasons (the maximum week across 2013–25 FBS games); pipeline uses each season's last regular-season week (15 in 2015–18 and 2021–23) | **Residual skew**: weight `week/17` vs `week/16`, and postseason values differ in 15-week seasons (see §2.6) |
| `04_fourth_down_model_old.ipynb` | n/a | Same final feature list as current | Superseded; not used |

`results/` (213 week files, 162,874 decisions) was regenerated on 2026-04-18 between 21:59 and 22:03 CDT, matching the last pipeline and model commits **[verified]**. The deployed v1 numbers therefore come from current code plus current artifacts.

---

## 2. Pipeline data contract

### 2.1 Entry points and upstream calls

Invocation: `scripts/run_week.sh -y YEAR -w WEEK -s regular|postseason` runs `python -m jobs --jobname week`, which calls `recommender.generate_recommendations`. All CFBD access is in `data_loader/data_loader.py` via the `cfbd` Python client. File caches are season-level parquet files under `data/`; they are overwritten in place, not immutable.

| Loader | CFBD endpoint | Granularity | Refresh behavior [code] |
|---|---|---|---|
| `load_games` | `GamesApi.get_games(year)` | season | Refetched if the week is missing |
| `load_plays` | `PlaysApi.get_plays(year, week, season_type)` | week | Appended to the season file |
| `load_weather` | `GamesApi.get_weather(year)` | season | **Patreon Tier 1+ endpoint** (see §4) |
| `load_venues` | `VenuesApi.get_venues()` | all | Cached forever |
| `load_lines` | `BettingApi.get_lines(year)` | season | Refetched **whenever any spread in the week is null**, which is most weeks |
| `load_elo` | `get_games` + `TeamsApi.get_teams` for **every year 1930 → year** | season | On a cache miss: about 190 calls cold, plus a forced refresh of the current year |
| `load_team_strengths` | `MetricsApi.get_predicted_points_added_by_game(year)` for year−1 and year | season | Refetched if the current week is missing |
| `load_advanced_team_stats` | `StatsApi.get_advanced_season_stats(year, start_week=1, end_week=w)` for w = 3..15 | 13 calls per season | **Only checks that the season exists in cache.** Mid-season it keeps serving stale weeks; missing weeks silently fall back to the Elo prior |
| `load_coaches`, `load_teams` | Coaches, teams | season | Postprocess only |

### 2.2 Coordinate systems and conventions (raw API to model input)

**Field position**

- CFBD `yards_to_goal` is from the **offense's** perspective (0 = opponent goal line). `yardline` (home-relative) is fetched but not used.
- Pipeline rules **[code]**:
  - keep `0 ≤ yards_to_goal ≤ 100`;
  - set `yards_to_goal == 0` to 1;
  - set `distance == 0` to 1;
  - cap `distance` at `yards_to_goal`.
- The training notebooks differ. The conversion notebook drops `distance == 0` and `ytg == 0` (a cell marked `#TODO DELETE THIS`). The WP notebook keeps them and filters `distance ≤ 40`.

**Clock**

- CFBD `clock.{minutes, seconds}` is time remaining in the period. Clipped to minutes [0, 15] and seconds [0, 59].
- `game_seconds_remaining = (4 − period)·900 + clock`, regulation only (`0 < period ≤ 4`). Overtime is excluded everywhere in the pipeline.
- **Which instant the clock refers to [verified, strong evidence]:**
  - In 2025 CFBD rows whose text starts with a snap timestamp like "(12:19)" (22.7% of plays), CFBD's clock is a median **5 s lower** than the text timestamp; 81% of those rows are lower.
  - 50% of last plays of Q2/Q4 show 0:00.
  - ESPN's own feed shows the same pattern: `clock.displayValue` 2:24 on a play whose text starts "(02:33)".
  - Conclusion: **the CFBD clock on a play row is the clock when the play ended (or was logged), not at the snap.**

**Scores**

- CFBD `offense_score` and `defense_score` are the score **after** the play **[verified]**:
  - on `Field Goal Good` rows, `offense_score == previous play + 3` 98.0% of the time;
  - on offensive TD rows, the score is ≥ previous + 6 98.6% of the time.
- Negative scores are clipped to 0.
- `score_diff = offense_score − defense_score`.

**Timeouts**

- CFBD `offense_timeouts` and `defense_timeouts` are clipped to [0, 3].
- Null rate on 4th downs: 0.2–0.5% in 2013–2024, **9.3% in 2025** **[verified]**.
- Values never increase within a half (0 of 6,422 team-halves in 2024) **[verified]**. That is internally consistent, but I can't verify accuracy.
- Pipeline imputation: `floor(−2.4387 · pct_half_played + 3.1631)`. `pct_half_played` ranges 0–0.5 despite the name, so this imputes 3 down to 1.
- **Training does not impute.** XGBoost sees NaN, and the kneel-out simulator treats NaN as zero timeouts.

**Home and possession**

- `is_home_team` is 0 if `neutral_site`, 1 if `offense == home_team`, else −1. **This is a join on display name**: CFBD play `offense` string vs game `home_team` string.

**Spread**

- `home_spread` is the first non-null of: consensus, teamrankings, numberfire, Bovada, ESPN Bet, DraftKings, Caesars, SugarHouse, William Hill NJ, Caesars CO, Caesars PA.
- Sign convention: negative means the home team is favored. The WP notebook's cell 10 checks for negative correlation with home−away Elo.
- `pregame_spread = home_spread` if the offense is home, else `−home_spread`. **Negative means the offense is favored.**
- Missing spreads are imputed with `regressor.pkl` from the two pregame Elos.

**Elo**

- Merged on `(season, week, team_id)`; `season_type` is **not** in the merge or the Elo week loop. See bugs B3/B4.

**Weather**

- CFBD `/games/weather` by game id: `temperature` °F, `wind_speed` mph, `precipitation`, `game_indoors`.
- Indoors: temperature 70, wind 0, precipitation 0.
- Missing values: `int(batch.mean())`. In the pipeline the batch is that week's fourth downs; in training it is the whole training set.

**Venue**

- CFBD venues: `elevation` (a string, in meters) is cast to float; missing elevation is imputed with the batch mean. Missing `grass` → False.

**Coaches**

- Joined on `(season, school name)` in postprocessing.

### 2.3 Derived pregame features

**Success rates** (`add_offense_success_rates`):

- **Observed rate:** CFBD advanced season stats for weeks 1..w (garbage time excluded) give the passing and rushing `successRate`, labelled as week `w+1`. That makes them strictly pre-game.
- **Prior:** `intercept + coef · pregame Elo` (JSON artifacts).
- **Missing observed value:** replaced with the prior. This covers weeks 1–3 always, and all of 2019, which has no advanced stats in cache. The loader comment says "There is no advanced team stats data for 2019 season" **[uncertain whether that is a CFBD gap or a failed fetch that got cached]**.
- **Blend:** `adjusted = prior · (1 − week/(max_week+1)) + observed · week/(max_week+1)`.
- **Postseason:** rows copy the last regular-season week's values.
- **Joins:** on team **display name**.

**Team strength:**

- Strict `< target week` window.
- Joined on team **display name**.
- Missing teams get `offense.pkl`/`defense.pkl` from Elo.

**Kneel-out and pressure features:** deterministic functions of clock, timeouts, down and score.

### 2.4 Post-decision states (how the three options are scored)

All three options assume **5 seconds** of clock runoff. For go and FG, the kneel-out features are recomputed on the new state **[code]**.

- **Go, converted:** the offense gains exactly `distance`.
  - If `yards_to_goal ≤ distance`: counted as a TD worth **+7** (no PAT modelling). The opponent then gets the ball at 80 yards to goal, 1st-and-10, with the roles flipped.
  - Otherwise: 1st down at `ytg − distance`, distance `min(10, …)`. This state was never in WP training; see §1.2.
- **Go, failed:** zero yards gained. The opponent gets the ball at `100 − ytg`, 1st and `min(10, 100 − ytg)`.
- **`exp_wp_go`** = `p_convert · WP_convert + (1 − p_convert) · WP_fail`.
- **FG make probability:** from the Heckman model, then overridden by hard-coded values by kick distance:

  | Kick distance | Probability |
  |---|---|
  | 55–56 yds | 0.04 |
  | 57–58 yds | 0.03 |
  | 59–60 yds | 0.02 |
  | 61–64 yds | 0.005 |
  | 65–70 yds | 0.001 |
  | over 70 yds | 0 |

- **FG made:** +3; the opponent starts at 80.
- **FG missed:** the opponent gets the ball at `100 − ytg` (NCAA previous-spot rule). **`game_seconds_remaining` is not decremented on this branch** (inconsistent with the others) **[code]**.
- **FG attempts from more than 60 yards to goal** are dropped from grading.
- **Punt:** `WP(opponent ball at the predicted field position)`, i.e. **WP of the expected field position**, not the expected WP over field positions.
- **Game over:** each branch forces WP to 0 or 1 when `pct_game_played` reaches 1.0.

### 2.5 Grading and outputs (`postprocessing.py`)

**Actual decision:** `add_decision` classifies the play by regex on `play_text` and `play_type` into rush, pass, punt, field_goal, etc.

- Kneels, timeouts, kickoffs, end-of-period rows, safeties and "other" are dropped.
- **Penalty plays are deliberately kept.** From the code comment: "we dont know if the penalty caused a replay or not".

**Recommendation:** one of seven labels, `Go | Field Goal | Punt | Go or Field Goal | Go or Punt | Field Goal or Punt | No Recommendation`, based on exact equality of expected WP rounded to 4 decimals.

- The code comment says "within 0.5% eWP"; **the code uses `== 0`**.

**`eWP_diff`:** the **minimum absolute pairwise gap among all three options**, not the recommended option's margin over the runner-up. Example: go 0.50 / FG 0.30 / punt 0.31 gives 0.01, not 0.19. **[code] bug.**

**Team and coach tendencies:** only rows where the recommendation is `Go` count. There, `wp_lost = exp_wp_go − exp_wp_(actual)`.

**Coach join** on `(season, school name)`:

- Keeps coaches with `hire_date ≤ start_date`, sorts by hire date ascending, and keeps the first row. That is the **earliest** eligible coach, although the comment says "most recenlty hired" **[code] bug**. Mid-season replacements are attributed to the departed coach.
- Rows with a null hire date are silently dropped.

**Output files:** writes `team_tendencies.parquet`, `coach_tendencies.parquet` and `game_decisions.parquet` **directly into `../cfb-4th-down-app/data`**. `generate_game_decisions` applies `dropna()` across all columns, so any row with a null logo or abbreviation disappears.

The v1 app is Python Dash, not React.

### 2.6 Bugs and train/serve mismatches, ranked

| ID | Severity | Issue | Evidence | Fix needs retrain? |
|---|---|---|---|---|
| B1 | **Critical** | **Post-play score used as the pre-decision state.** The same contamination is in training: 8.2% of 4th-down run/pass training rows are offensive TDs carrying +6 with label 1. That inflates the learned effect of `diff_time_ratio`, the conversion model's #2 feature, which has a +1 monotone constraint. FG selection training has +3 on the ~74% of attempts that were made. | Re-grading 2024–25 with the scores corrected: 4,517 of 25,822 rows affected; **26.6% of those flip recommendation (4.65% of all)**; mean absolute WP change 0.065–0.073 per option. On made FGs, recommendations go FG 2,768 / go 1,029 / punt 55 → 2,986 / 826 / 40 **[verified]**. Caveat: my correction assumes all FG-good/TD rows are post-play; about 2% are not. | **Yes** (WP, conversion, FG selection). The punt model is unaffected. |
| B2 | High | **Clock is end-of-play**, about 5 s after the snap, in both training and inference. Consistent in batch, but live pre-snap clocks will be ~5 s higher than anything seen in training. It matters at the end of halves (kneel-out features). | §2.2 **[verified]** | Yes, to align with live |
| B3 | High | **Postseason games get preseason Elo.** The Elo loop groups by `week` only, so postseason week 1 is processed with regular-season week 1. Training merges `drop_duplicates(['season','week','team_id'], keep='first')` to the same values. | Western Michigan 2024: postseason Elo 1561.437 = regular week-1 Elo **[verified]** | Yes |
| B4 | High | **Bowl results leak into that season's regular-season Elo from week 2 onward**, for every historical season. This is training-feature leakage that live data can never reproduce. | 54 of 54 bowl teams with no regular-season week-1 game have a different Elo at their first regular-season game than preseason **[verified]** | Yes |
| B5 | Medium | **FG inverse Mills ratio computed from Φ(Xβ) instead of Xβ.** The pipeline calls `selection_model.predict(X)`, which returns a probability; training used `predict(X, linear=True)`. | Probe: probability 0.371 vs linear index −0.329. Fixing it: FG make probability −0.026 (40–50 yd), −0.034 (50–55 yd); 0.60% of recommendations flip **[verified]** | No: inference-only fix |
| B6 | Medium | **WP model evaluated out of distribution** on 1st-and-goal (distance < 10) post-conversion states. | Training filter, §1.2 **[code]** | Yes |
| B7 | Medium | **Weather imputation uses the batch mean, cast with `int()`.** Non-idempotent across batch composition. If every row in a batch lacks weather (e.g. a single live game), `int(nan)` raises `ValueError`. | [code] | No, but needs a fixed constant |
| B8 | Medium | **Advanced-stats cache never refreshes in-season.** Weeks fetched after the first run fall back to the Elo prior unless `--force` is used. | [code] | No |
| B9 | Medium | **Success-rate blend weight mismatch.** Training: `week/17`. Pipeline: `week/(last_regular_week + 1)`. In 15-week seasons, training postseason rows use the pure prior; the pipeline uses week-15 values. | [verified] max weeks per season | Minor retrain or align |
| B10 | Medium | **Timeout imputation differs.** Training uses NaN; the pipeline uses a formula. Matters now that 2025 is 9.3% null. | [verified] | Align |
| B11 | Low | **`eWP_diff` is the minimum pairwise gap**, not the margin. Comment says 0.5% tolerance but the code tests equality. | [code] | No |
| B12 | Low | **Coach join keeps the earliest hire**; null hire dates dropped; `dropna()` drops rows silently. | [code] | No |
| B13 | Low | **Punt constant below 40 yards to goal:** 80 in the pipeline vs 89 in the notebook. The punt EV plugs in a point estimate (WP of expected field position). | [code] | No |
| B14 | Low | **FG-miss branch** does not decrement `game_seconds_remaining`. | [code] | No |
| B15 | Low | **Display-name joins** (home/away, strengths, success rates, coaches), against the `CLAUDE.md` canonical-ID rule. | [code] | No |
| B16 | Info | **Random game splits and unseeded Optuna.** Retraining will not reproduce the artifacts, and 2013–2025 backfill grades are in-sample. | [code] | n/a |
| B17 | Info | **Unexplained anomaly** in v1 `todo.txt`: "2025 Vanderbilt vs Missouri 4th&4 93 yards to go is it recommending go with 7.8% WP gain over Punt?" Not investigated here. | — | Unknown |

---

## 3. ESPN live format

### 3.1 Official status

- **Not officially documented.** ESPN publishes no developer documentation or terms of use for `site.api.espn.com`. Everything known comes from community reverse-engineering: the widely cited [akeaswaran gist](https://gist.github.com/akeaswaran/b48b02f1c94f873c6655e7129910fc3b) and [pseudo-r/Public-ESPN-API](https://github.com/pseudo-r/Public-ESPN-API). These are the endpoints ESPN's own site and apps use.
- **What I verified directly:** response shapes, by fetching live data during in-progress FBS games (86 events: 29 in progress, 47 final, 10 scheduled).

### 3.2 Endpoints observed

| Endpoint | Use | Notes observed |
|---|---|---|
| `GET https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300` | All FBS games for the current day and live situation | 1.28 MB; `cache-control: max-age=4`; no auth |
| `GET .../college-football/summary?event={id}` | Full play-by-play, drives, odds, venue, weather, ESPN win probability | `cache-control: max-age=2–5` |

**Scoreboard, per event** **[verified]**:

- `status.clock` (seconds, float), `status.displayClock`, `status.period`, `status.type.state` (`pre|in|post`)
- `competitions[0].neutralSite`, `venue.indoor`
- `competitors[].{homeAway, score, team.{id, abbreviation, location, color, alternateColor, logo, conferenceId}}`
- `weather.{temperature, highTemperature, conditionId}`
- `odds` was **null** for the in-progress game checked
- `competitions[0].situation`:
  - `down, distance, yardLine, downDistanceText, shortDownDistanceText, possessionText, isRedZone, homeTimeouts, awayTimeouts, possession`
  - `lastPlay.{id, type, text, scoreValue, team.id, probability.{homeWinPercentage, secondsLeft}, statYardage, drive, start.yardLine, end.yardLine}`

**Summary** **[verified]**:

- `drives.previous[].plays[]` and `drives.current.plays[]`. Each play has:
  - `id, sequenceNumber, type.{id,text}, text, awayScore, homeScore, period.number, clock.displayValue`
  - `scoringPlay, isPenalty, isTurnover, statYardage, wallclock, modified`
  - `start` and `end`, each with `{down, distance, yardLine, yardsToEndzone, downDistanceText, possessionText, team.id}`
- Other top-level keys:
  - `pickcenter[]`: provider, `spread`, `overUnder`, `favoriteAtOpen`
  - `gameInfo.venue.grass`
  - `gameInfo.weather.{temperature, highTemperature, lowTemperature, conditionId, gust, precipitation}`
  - `winprobability[]`: ESPN's own model, one entry per play
  - `header`, `boxscore`, `scoringPlays`

### 3.3 Conventions that differ from CFBD or are easy to get wrong

- **`yardLine` is measured from the home team's goal line**, not the offense's. Examples:
  - Buffalo (away) at its own 9 → `yardLine` 91.
  - Florida (home) at its own 29 → 29.
  - Florida at the opponent's 10 → 90.

  **`start.yardsToEndzone`** (summary plays only, not `situation`) is offense-relative and equals CFBD `yards_to_goal`. From `situation` you must derive `ytg = 100 − yardLine` if the offense is home, else `yardLine` **[verified on 6 games]**.
- **`situation.possession` was null in 15–18 of 29 live games** across seven polls over two minutes, including mid-drive states with a populated `downDistanceText` **[verified]**. The offense has to come from `drives.current.team`, the last play's `end.team.id`, or by parsing `possessionText`. This is the main parsing risk.
- **`play.clock.displayValue` is end-of-play**; the parenthetical at the start of `text` is the snap clock. Examples: "(12:19)" → 12:18, "(11:02)" → 10:57, "(05:19)" → 5:11 **[verified]**. The pre-snap state for a pending fourth down is `status.clock` / `displayClock`.
- **`awayScore`/`homeScore` on a play are post-play** (a made FG row shows the +3). For a pending fourth down, `competitors[].score` is the correct pre-snap score. **Live data therefore gives the pre-snap state that v1 never trained on** (B1).
- **Penalty no-plays appear with `start.down == 4`**, e.g. "PENALTY CU False Start … NO PLAY". Use `isPenalty` plus text to filter.
- **Play records are revised after the fact.** A made FG with `wallclock` 21:37:52 had `modified` 21:45; a punt 21:54:30 → 22:02; another FG 22:02:12 → 22:15. Anything graded live must be regradeable.
- **Weather is a forecast / current-conditions feed** (AccuWeather link), not CFBD's source:
  - `precipitation: 34` alongside "Mostly cloudy" reads as a **percentage chance**, not inches **[uncertain]**.
  - There is **no sustained wind speed**, only `gust`.
  - The scoreboard's `weather.displayValue` was "38" alongside `temperature: 80` **[unexplained]**.
- **Spread:** `pickcenter.spread` was present in the summary (DraftKings, "FLA −51.5"). It is **unclear whether it stays frozen at the pregame close or moves with live lines** **[uncertain]**. Snapshot it before kickoff.

### 3.4 Reliability concerns

- **No contract.** Fields, URLs and access policy can change without notice.
- **Access blocks reported.** Community comments on the gist report **HTTP 403s beginning 2026-08-05**, with a workaround host `site.web.api.espn.com` **[uncertain; my requests to `site.api.espn.com` succeeded on 2026-09-13]**.
- **Null or stale fields mid-game:** `possession` (above), and `odds` null on the scoreboard.
- **Retroactive edits** to play records (above).
- **Latency: not measured properly.** For 6 live games, the newest play's `wallclock` was 58–280 s older than my fetch. That mixes feed latency with dead time (TV timeouts, stoppages), so the figure is not a latency number.

  The fourth-down window is the time between the 3rd-down play being logged and the 4th-down snap, typically tens of seconds to a couple of minutes **[uncertain]**. Plan to detect it with a poller at a cadence of about 15–20 s. **A 5-minute GitHub Actions cron will miss most windows** (`automation.md` already says as much).

### 3.5 ESPN ↔ CFBD ID mapping

- **Team IDs:** identical. All 172 teams on today's ESPN scoreboard matched CFBD 2025 `teams.id`, with identical school names **[verified]**.
- **Game IDs:** CFBD game IDs have ESPN's event-ID format (2025: `401756846…`; ESPN 2026 events: `401856672…`). CFBD is widely understood to reuse ESPN event IDs, but **I did not check a 2026 game against CFBD** (no API key was used) **[uncertain]**. If this holds, mapping is an identity join, not fuzzy matching.
- **Venue IDs:** ESPN venue `3634` (Ben Hill Griffin); I did not check CFBD venue IDs **[uncertain]**. v1 needs CFBD venue elevation.

### 3.6 Feature-by-feature: can each model input be fed live?

Legend:

- **Direct**: present in ESPN live JSON.
- **Derived**: computed from live fields.
- **Pregame**: must be precomputed before kickoff from CFBD history; stable during the game.
- **Unavailable**: not obtainable live in the units the model was trained on.

| Input | Used by | Live status | Source / notes |
|---|---|---|---|
| `down`, `distance` | WP, conversion, FG selection | Direct | `situation.down`, `.distance` |
| `yards_to_goal` | all | Derived | `situation.yardLine` (home-relative) + offense identity. Offense identity is unreliable (`possession` often null) |
| `offense_score`, `defense_score`, `score_diff` | WP, FG selection | Direct | `competitors[].score`, mapped via offense. **Pre-snap**, whereas training used post-play (B1) |
| `period`, clock → `pct_game_played`, `game_seconds_remaining`, `seconds_left_in_half` | WP, FG selection | Direct / Derived | `status.period`, `status.clock`. **Pre-snap**, whereas training used end-of-play (B2) |
| `offense_timeouts`, `defense_timeouts` | WP | Direct | `situation.homeTimeouts/awayTimeouts` + offense identity. Accuracy unverified |
| `is_home_team` | WP, conversion, FG selection | Direct | `homeAway`, `neutralSite` |
| `diff_time_ratio`, `pressure_rating`, `seconds_after_kneelout`, `seconds_after_punt_and_opponent_kneelout` | WP, conversion, FG outcome | Derived | Deterministic functions of the above |
| `pregame_spread` → `spread_time_ratio` | WP | Pregame | Snapshot CFBD `/lines` or ESPN `pickcenter` before kickoff. Fall back to the Elo regression. Training used CFBD consensus-first lines, so the provider mix is a small skew |
| `pregame_offense_elo`, `pregame_defense_elo` | WP, FG, punt, success-rate prior, strength imputation | Pregame | Replay in-house Elo through the last completed week (needs CFBD final scores). Must fix B3/B4 |
| `offense_strength`, `defense_strength` | conversion | Pregame (season-aggregate, prior weeks only) | CFBD PPA by game for the prior 10 weeks, then an SLSQP fit. **Needs last week's PPA published before this week's games (timing unverified).** CFBD-proprietary metric, so it is not provider-replaceable |
| `offense_pass_success_adjusted`, `offense_rush_success_adjusted` | conversion | Pregame (season-aggregate, prior weeks only) | CFBD advanced season stats through the previous week, blended with the Elo prior. Safe live **only if refreshed weekly** (B8) |
| `season` | FG outcome | Direct | trivial |
| `game_indoors` | FG selection; weather defaults | Direct | ESPN `venue.indoor` |
| `grass` | FG selection | Direct / Pregame | ESPN `gameInfo.venue.grass`, or CFBD venues |
| `elevation` | FG, punt | Pregame (static) | CFBD venues. Needs the ESPN→CFBD venue ID check |
| `temperature` | conversion, FG selection, punt | Direct, different source | ESPN AccuWeather °F. Training used CFBD observed weather. CFBD weather is Tier 1 and it's **unverified whether it's populated before or during games** |
| `wind_speed` | FG selection, FG outcome, punt XGB (conversion booster ignores it) | **Unavailable** in training units | ESPN has only `gust`. Options: external forecast API (new provider), CFBD Tier 1 if populated pre-game [uncertain], or a fixed imputation constant |
| `precipitation` | conversion, punt XGB | **Unavailable** in training units | ESPN value appears to be % chance. Same options as wind |

**Answer.** Every v1 model can be fed in real time. None of its inputs depends on post-game data. The season-aggregate inputs (success rates, team strengths, Elo) are built strictly from earlier weeks in both training and pipeline code **[code]**, so a pre-kickoff snapshot job can materialize them. The things that would quietly break a live pipeline are different from the ones you'd expect:

1. **Weather.** Wind speed and precipitation aren't available live in the training units. Temperature comes from a different source. Imputing a constant is workable: wind has zero splits in the conversion booster, and precipitation and wind are small effects in the FG and punt models. **This affects three of the six artifacts.**
2. **Semantic skew.** Live gives pre-snap score and clock. v1 trained on post-play score and end-of-play clock. For plays that score, a live grade and v1's own post-game batch grade for the same play will differ, and on 26.6% of those the recommendation itself flips (B1).
3. **Pregame staleness.** The pregame snapshot must actually refresh (B8), and must handle postseason correctly (B3).
4. **Offense identity.** `situation.possession` is frequently null. A wrong offense mirrors `yards_to_goal`, the timeouts and the scores.
5. **Batch-mean imputation crashes** on a one-game batch (B7).
6. **Operational.** Poll cadence (§3.4) and ESPN access stability.

---

## 4. Conflicts between the written plan and v1

Each item lists what the plan says, what v1 actually does, and **which side should change**.

### 4.1 `docs/api-contract.md`

| # | Plan | v1 reality | Change | Why |
|---|---|---|---|---|
| C1 | `recommendation`: `"go" \| "punt" \| "field_goal"` | Seven labels including ties and `No Recommendation` | **Contract**: add a tie or `null` case, or define a deterministic tie-break | Exact ties happen at 4-decimal rounding; the contract must say what the UI shows |
| C2 | `wp_go`, `wp_punt`, `wp_field_goal` always floats | v1 always computes all three, but FG is forced to 0 beyond 70-yard kicks and FG decisions from over 60 ytg are dropped; there is no notion of an infeasible option | **Contract**: allow `null` for options the model treats as infeasible (FG from midfield, punt from the 2), and define feasibility rules in the pipeline | Otherwise the UI shows a meaningless "field goal 0.31" from your own 20 |
| C3 | `wp_delta = wp(actual) − wp(recommendation)` | No such field. v1's `eWP_diff` is the minimum pairwise gap (B11), and `wp_lost` exists only when the recommendation is Go | **Pipeline** (compute it fresh); contract stays | Contract definition is correct; v1's is buggy |
| C4 | Simulator `margin` / `confidence` | Not in v1; v1's closest field is wrong (B11) | **Pipeline** | Define margin as best minus second-best |
| C5 | `offense_score`, `defense_score`, `clock` on a Decision imply the situation at the decision | v1 values are **post-play** score and end-of-play clock (B1, B2) | **Pipeline**: use pre-snap state (previous play's post-score; snap time) and retrain | A card that shows 20–17 for a FG that made it 20–17 is wrong on its face |
| C6 | `yard_line` and `yards_to_goal` both present; examples give equal values (22/22, 38/38) | v1 has only offense-relative `yards_to_goal`; ESPN `yardLine` is home-relative | **Contract**: define `yard_line` (e.g. "own 22" / "opp 38" as side + number) or drop it | As written the two fields are indistinguishable, and a live implementer would pass ESPN's home-relative number straight through |
| C7 | Decision, scoreboard week and week-in-review keyed by `season` + `week` only | `CLAUDE.md` quirk; postseason week 1 collides with regular week 1. v1's Elo bug B3/B4 is exactly this | **Contract**: add `season_type` to the Decision object and to `/scoreboard/week/…` and `/week-in-review/…` paths (e.g. `/week/2026/postseason/1`) | The same collision already corrupted v1 |
| C8 | `wp_series` across the whole game (about 200 points) | The v1 WP model was trained only on 1st-and-10 and 4th-down snaps; it has never seen 2nd/3rd down | **Plan** (sitemap and contract): either retrain WP on all downs or chart only at 1st-and-10/4th-down points | Evaluating on 2nd/3rd down is out of distribution |
| C9 | Simulator inputs: `distance, yards_to_goal, score_diff, period, clock, offense_rating, defense_rating` | Model needs: both raw scores (not just the difference), both timeouts, pregame spread, two Elos, two PPA strengths, two success rates, home/neutral, temperature, wind, precipitation, elevation, grass, indoor, season | **Contract**: define simulator defaults for every hidden input, and map `offense_rating` / `defense_rating` to a documented composite | "Same inputs → same answer" is false unless the hidden inputs are pinned |
| C10 | `/simulate/table` precomputed lookup covering the common input space | With about 25 model inputs, a full table is impractical unless most are fixed at defaults | **Plan**: accept a reduced table (fix team/weather at league average) or a server endpoint | Explicit trade-off, not a free choice |
| C11 | `coach_id: "odom-barry"`, `coach_name` | v1 has no coach ID; it joins coaches by school display name with the earliest-hire bug (B12) | **Pipeline** (build a coach ID table); contract fine | `CLAUDE.md` canonical-ID rule |
| C12 | `outcome: "punt_downed"` etc. | v1 has no outcome taxonomy, only CFBD `play_type` plus text regexes | **Pipeline** (define the taxonomy); contract should enumerate the values | Currently unspecified |
| C13 | `/health` returns model version; simulator cache keyed on model version | v1 has no model versioning; artifacts are unversioned files behind absolute symlinks | **Pipeline** | Required by the plan, absent in v1 |

### 4.2 `docs/data-pipeline.md`

| # | Plan | v1 reality | Change | Why |
|---|---|---|---|---|
| P1 | Stages: fetch raw plays → filter → model | The model stage needs **ten CFBD datasets**: games, plays, lines, weather, venues, teams (1930+ for Elo), PPA by game (two seasons), advanced season stats (13 cumulative calls), coaches, plus derived Elo and team-strength fits | **Doc**: add a "pregame features" stage (Elo, strengths, success rates, spread, venue/weather) with its own cache and snapshot per game | The stage diagram omits most of the data the models consume |
| P2 | Raw cached at `data/raw/{season}/{week}/{game_id}.json`, immutable | v1 caches season-level parquet, overwritten in place | **Doc**: path needs `season_type`, and non-play datasets aren't per-game (per-season/per-week files) | C7 collision; many endpoints are season-scoped |
| P3 | "Reprocessing never re-fetches … retrain, replay from disk, no API calls" | Features like advanced stats, PPA and lines are themselves revised upstream, and Elo depends on all prior games | **Doc**: replay must use the *feature snapshot as of the game*, not today's recomputation, or backfilled grades use information unavailable at the time | Same class of leak as B4 |
| P4 | CFBD allows "roughly 200/hour" | CFBD API tiers: **Free = 1,000 calls/month**; Tier 1 ($1/mo) = 5,000 calls/month **and is required for weather data**; live play-by-play requires Tier 2 ($5/mo) ([source](https://collegefootballdata.com/api-tiers)) | **Doc** | The budget model is wrong by an order of magnitude, and v1's weather dependency costs money |
| P5 | Stage 2 excludes garbage time, pre-snap penalties, kneels | v1: no garbage-time filter; **keeps** penalty plays on purpose; kneel filter by regex; **excludes all overtime** | **Doc**: state that overtime is ungraded (models can't do overtime) and decide the penalty policy explicitly | Silent differences would change counts vs v1 |
| P6 | WP "given yards to goal, down, distance, score differential, time remaining, timeouts, possession" | Also raw scores, pregame spread, both Elos, home/neutral, two kneel-out simulations | **Doc** (or retrain to the doc's leaner spec) | Methodology page must describe the real model |
| P7 | Conversion "optionally adjusted by offense and defense quality" | Not optional: weather, two success rates, two strengths, `diff_time_ratio` are inputs | **Doc** | Same |
| P8 | FG "probability of making from a given distance" | Heckman two-stage selection correction with weather, elevation, pressure, season trend, Elo, plus hard-coded overrides for 55+ yards | **Doc** | Same; hard-coded values must be disclosed (`CLAUDE.md` "never invent stats") |
| P9 | `wp_punt = E[WP(opponent ball at resulting field position)]` | v1 computes `WP(E[field position])`; the model only gives a point estimate; below 40 ytg it assumes 80 | **Doc**, unless you retrain punt as a distribution | v1 can't compute the expectation the doc describes |
| P10 | `wp_go = p_convert·WP(first down at new spot) + …` | Matches, with undocumented assumptions: gain exactly `distance`, TD = +7, failure = 0 yards, 5 s runoff; FG make → opponent at 80 | **Doc** (list the assumptions) | Methodology honesty |
| P11 | `recommendation = argmax` | Tie categories (C1) | **Doc** + contract | — |
| P12 | Coach attribution: team-season, mid-season splits, `is_interim`, never guess | v1 guesses (earliest hire by school name), drops null hire dates | **Pipeline** (new work; nothing reusable from v1). CFBD coach records give hire dates and per-season rows; whether they support mid-season boundaries is **[uncertain]** | Doc is right; v1 is wrong |
| P13 | Model versioning, invalidation, full replay | None in v1 | **Pipeline** | — |
| P14 | Backfill 2013–2025 | Models were trained on 2013–2025 with random game splits, so backfilled grades are in-sample | **Doc**: note it on Methodology, or retrain with temporal holdout | Credibility |

### 4.3 `docs/automation.md`

| # | Plan | Reality | Change | Why |
|---|---|---|---|---|
| A1 | "Everything here fits in free tiers" | Hourly `game-check` about Aug–Jan is ~720 CFBD calls/month on its own; `process` needs games, plays, lines, weather, PPA, advanced stats (≥ 20 calls per week cold); weather needs Tier 1 | **Doc**: budget CFBD Tier 1 minimum, and use ESPN (free, unofficial) for `game-check` | Free tier is 1,000/month |
| A2 | `live-poll` "grades fourth downs as they happen" using `CFBD_API_KEY` | CFBD live play-by-play is Tier 2. `CLAUDE.md` says ESPN for live | **Doc**: live-poll uses ESPN plus the pregame snapshot; no CFBD in the live loop | Contradiction inside the plan |
| A3 | `live-poll` every 2 min, starting on 5-minute Actions cron | Fourth-down windows are short (§3.4) | **Plan**: already acknowledged; the pending card should not ship on option 1 | — |
| A4 | Week-in-review Tuesday 06:00 "after the reprocessing window has caught most corrections" | Window is 7 days; Saturday games are only ~3 days old on Tuesday | **Doc**: either say "partial window" or run Sunday of the following week | Internal inconsistency |
| A5 | "Roll back by replaying from raw disk cache with the previous model version" | Needs versioned pregame feature snapshots (P3) as well as raw plays | **Doc** | — |

### 4.4 `docs/sitemap.md`, `README.md`, `CLAUDE.md`

| # | Plan | Reality | Change | Why |
|---|---|---|---|---|
| S1 | README: "every fourth down, every game, graded **live**" | Not credible on v1 artifacts (§3.6, B1) | **README** until live grading ships | Don't promise it on the tagline |
| S2 | Sitemap §1 pending decision card "shows the recommendation before the coach acts" | Mechanically feasible (§3.6) but needs retrained pre-snap models, a pregame snapshot job, an in-app poller, and robust offense detection | **Sitemap / build order**: move to a later phase | See §5 |
| S3 | Sitemap §2 game-page WP chart across the game | C8 | **Plan** or retrain | — |
| S4 | Sitemap §5 simulator "optionally team quality" | Team quality is required (four inputs plus spread) | **Sitemap**: define defaults | C9 |
| S5 | Sitemap §6 "how the four component models fit together" | Six fitted artifacts, five auxiliary regressions, two derived ratings, hard-coded rules (§1) | **Sitemap / Methodology** | Honesty |
| S6 | Build order Phase 2: "Game page and live scoreboard reading real data" | Live grading depends on retraining | **Build order**: Phase 2 = batch-graded game page and "latest week" scoreboard; live grading later | §5 |
| S7 | `CLAUDE.md`: "Canonical IDs … never join on display names" | v1 joins on names in five places (B15) | **v1 code** is not reused as-is; rule stands. ESPN and CFBD share team IDs, which makes this easy | — |
| S8 | `CLAUDE.md`: "Keep providers replaceable" | Two conversion-model inputs (strengths from CFBD PPA; success rates from CFBD advanced stats) are **CFBD-proprietary metrics**; replacing CFBD means retraining without them or reimplementing CFBD's EPA model | **`CLAUDE.md`**: state that the model is coupled to CFBD metrics, or retrain on provider-neutral features (own EPA/success rate from raw PBP) | The rule cannot hold for the models as built |
| S9 | `CLAUDE.md`: Frontend stack React; "Rebuild of cfb4thdown.com" | v1 app is Python Dash with parquet files written cross-repo by the pipeline | No change; note only | v1 frontend is not reusable code |
| S10 | `CLAUDE.md` Live data: evaluate "mapping ESPN games to CFBD games" | Team IDs identical; game IDs very likely identical (§3.5) | **`CLAUDE.md`**: downgrade from risk to a one-off verification | Good news |
| S11 | `CLAUDE.md`: "Never invent stats" | v1 embeds invented constants that shape user-facing numbers: FG make probability 0.04 → 0 beyond 55 yards, punt 80 ytg inside the 40, 70 °F indoors, timeout imputation line, 5 s runoff, TD = 7 | **Methodology**: disclose them. They are model assumptions, not stats, but readers will see their effects | — |
| S12 | `.claude/commands/verfiy.md` | Filename typo; README advertises `/verify` | **Repo** | Minor |

---

## 5. Verdict

**Retrain.** Use the v1 notebooks as the recipe, not a from-scratch rebuild. **Do not ship the current artifacts behind user-facing numbers. Cut live grading from the first data phase.**

Why not "reuse as-is":

- **B1 alone changes the recommendation on about a quarter of scoring plays.** Its contamination is inside the training data of the WP, conversion and FG-selection models, so no inference-side patch removes it. Fixing only the inference side would make v2 grades differ from v1's published numbers anyway, so v2 cannot claim continuity with v1 either way.
- **B3/B4 (Elo) and B6 (WP never saw 1st-and-goal)** are also training-side.

Why not "reuse with modification":

- The only fixes that don't need retraining are B5 (FG inverse Mills ratio), B7, B8, B11–B15. They are worth doing, but they leave the largest error in place.
- The punt model is the exception. It has no score inputs and no training leak apart from Elo (B3/B4 affect its Elo inputs slightly). **Reuse the punt model with modification:** pick 80 vs 89 for short punts, export the OLS coefficients to JSON, and retrain alongside the others once Elo is fixed.

What a retrain should change, in order of impact:

1. **Build every training row from the pre-snap state:** the previous play's post-play score, and the snap clock from the play-text timestamp where present, otherwise the previous play's clock. This is exactly the state ESPN provides live, so the retrain also removes the live/batch skew.
2. **Fix Elo `season_type` handling** (B3/B4), and add `season_type` to every join.
3. **Train WP on all downs**, or at least include 1st-and-goal. This also unblocks the game-page WP chart (C8).
4. **Weather.** Decide whether weather earns its cost: CFBD Tier 1, no live wind or precipitation, and it's a new provider dependency. The saved conversion booster makes no use of wind at all. Dropping wind and precipitation, and keeping ESPN temperature plus indoor/grass, removes the only inputs unavailable live.
5. **Replace display-name joins with IDs**, pin the environment, export linear models to JSON, seed Optuna, use a temporal holdout, and version the models.
6. **Decide whether to keep CFBD-proprietary PPA and success-rate inputs** or derive provider-neutral equivalents from raw play-by-play (S8).

**Live scoreboard.**

- **The models are not the obstacle.** Every input is live-available, derivable or precomputable, except wind speed and precipitation.
- **What's missing before a pending-decision card is trustworthy:**
  - (a) models trained on pre-snap semantics;
  - (b) a pregame feature snapshot job;
  - (c) robust offense detection given null `possession`;
  - (d) an in-app poller at roughly 15–20 s;
  - (e) a regrade path for ESPN's retroactive edits;
  - (f) a fallback for ESPN access blocks.
- **Recommended phasing:**
  - **Phase 2:** batch-graded game pages, plus a "latest week" scoreboard. An ESPN live *score* ticker without grades is fine.
  - **Phase 3 or later:** pending-decision card and live WP deltas, once the retrained models and poller exist.
- **Update to the docs:** `README.md` tagline, `sitemap.md` build order and `automation.md` live-poll per §4.

**Open questions to resolve before retraining:**

- Does CFBD's weather endpoint have values before or during games?
- Does ESPN `pickcenter.spread` stay frozen at kickoff?
- Do CFBD 2026 game and venue IDs equal ESPN's?
- Is 2019 advanced-stats data really absent in CFBD?
- When is CFBD per-game PPA published after a Saturday?
- What causes the Vanderbilt–Missouri anomaly (B17)?

---

### Sources

- [ESPN's hidden API endpoints (community gist, akeaswaran)](https://gist.github.com/akeaswaran/b48b02f1c94f873c6655e7129910fc3b)
- [pseudo-r/Public-ESPN-API (community documentation)](https://github.com/pseudo-r/Public-ESPN-API)
- [CollegeFootballData API access tiers](https://collegefootballdata.com/api-tiers)
- Live ESPN responses fetched 2026-09-13 00:41–00:46 UTC: `site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300` and `/summary?event=401856672|401866414|401860881`
