# API contract

Base: `/api/v1`. JSON only. No authentication. Interactive docs at `/api/v1/docs`.

Implemented in `backend/app/api/`:
- Phase 2: `/scoreboard/latest`, `/scoreboard/week`, `/games`, `/games/:id`, `/teams`, `/ticker`, `/health`.
- Phase 3: `/punt-index`, `/punt-index/:subject/:id`, `/week-in-review/:season/:week`, `/week-in-review/latest`.

- Phase 4: `/simulate`.
- Phase 6: `/scoreboard/live`, live grades on `/games/:id`, and WP deltas in `/ticker`.

Every endpoint is served from cache. A user request never triggers an upstream call to CollegeFootballData — if the cache is cold, return what we have with a stale marker rather than blocking.

## Conventions

- Snake case in JSON.
- Win probabilities are floats 0-1. **Format for display at the edge, not in the API.**
- WP deltas are signed floats: `-0.094` means nine and a bit points of win probability surrendered.
- Timestamps are ISO 8601 UTC with `Z`.
- IDs are strings, even when they look numeric.

Every response carries a freshness envelope:

```json
{
  "data": { },
  "meta": {
    "generated_at": "2026-09-12T18:04:11Z",
    "stale": false,
    "source": "cache"
  }
}
```

`stale: true` means we're serving past the intended TTL because the pipeline is behind. The frontend should show a quiet indicator, not an error.

---

## Live scoreboard

### `GET /scoreboard/live`

Powers the home page. Single request, everything the page needs.

```json
{
  "data": {
    "games_live": 12,
    "games_total": 58,
    "fourth_downs_today": 87,
    "wp_lost_today": 0.048,
    "followed_model_rate": 0.64,
    "pending": {
      "game_id": "401628319",
      "offense": { "id": "2483", "name": "Oregon", "abbreviation": "ORE" },
      "defense": { "id": "264", "name": "Washington", "abbreviation": "WSH" },
      "offense_is_home": true,
      "home_score": 31,
      "away_score": 28,
      "period": 2,
      "clock": "6:41",
      "down": 4,
      "distance": 1,
      "yard_line": 22,
      "yards_to_goal": 22,
      "recommendation": "go",
      "confidence": "close",
      "margin": 0.025,
      "wp_go": 0.786,
      "wp_punt": null,
      "wp_field_goal": 0.761
    },
    "decisions": [ /* Decision objects, sorted by abs(wp_delta) desc */ ],
    "ticker": [
      {
        "game_id": "401628201",
        "away": "PUR", "away_score": 17,
        "home": "MSU", "home_score": 21,
        "status": "live",
        "period": 4,
        "clock": "06:12",
        "wp_delta_last": -0.094
      }
    ]
  }
}
```

`offense_is_home` says how to read `home_score`/`away_score` from the offense's side. `pending` is `null` when no game is sitting on a fourth down. The frontend must handle it appearing and disappearing between polls without layout shift.

**Cache:** 20s while any game is live, 1h otherwise.

As built (Phase 6):
- **Today's slate:** "today" is every game on ESPN's current scoreboard that is live or kicked off in the last 18 hours.
- **`decisions`:** live grades (`source: "espn"`) for games CFBD hasn't graded yet, plus batch grades (`source: "cfbd"`) for those it has, sorted by `abs(wp_delta)`.
- **`pending`:** the live game on fourth down latest in its game.
  - `pending_all` lists every one.
  - Each carries `polled_at` (when the scoreboard was read) and `timeouts_uncertain` (within 5 minutes of the end of a half).
  - A pending card older than 90 s is dropped.
- **`ticker`:** entries carry `start_date`; `wp_delta_last` is the most recent graded fourth down's delta for that game.
- **`meta.source`** is `"live"`. `meta.stale` is true when the ticker or live poll is more than 2 minutes behind during live games.
- **Cache:** 10 s. With no slate, it returns zeros and `pending: null`, and the home page shows `/scoreboard/latest` instead.

### `GET /scoreboard/week/:season/:week?season_type=regular&limit=50`

Same shape, for one week, plus week fields. Used as the home page (latest week) and the off-season fallback.

- `week` is **CFBD's week number**, which can differ from ESPN's. `season_type` is `regular` (default) or `postseason`; a week number alone is ambiguous across season types.
- `pending` is always `null` and `games_live` is `0`; `ticker` is empty (use `GET /ticker`).
- `fourth_downs_today`, `wp_lost_today` and `followed_model_rate` cover the whole week.
- `decisions` holds the `limit` highest-impact decisions (max 500); `decisions_total` counts all of them.

Additional fields:

```json
{
  "season": 2026, "week": 2, "season_type": "regular",
  "is_complete": false,
  "games_graded": 77,
  "wp_lost_per_game": 0.05,
  "decisions_total": 1063,
  "games": [ /* Game summaries (see GET /games) */ ]
}
```

`wp_lost_per_game` is `wp_lost_today` divided by the games with at least one graded fourth down.

**Cache:** 5 min / 1h CDN once the week is complete, 30s / 60s CDN while in progress.

### `GET /scoreboard/latest?limit=50`

`/scoreboard/week` for the most recent week that has graded decisions.

### `GET /ticker`

Scores for the ticker, from ESPN's scoreboard, refreshed server-side every 30s while games are live and every 10 min otherwise. Never fetched per request.

```json
{
  "data": {
    "games_live": 7,
    "games": [
      { "game_id": "401858219", "away": "GASO", "away_score": 7, "home": "CLEM", "home_score": 22,
        "status": "live", "period": 4, "clock": "3:10", "start_date": "2026-09-13T01:30Z", "wp_delta_last": null }
    ]
  },
  "meta": { "generated_at": "2026-09-13T04:52:56Z", "stale": false, "source": "espn" }
}
```

`wp_delta_last` stays `null` until live grading. `stale` is true when the last refresh is older than 3 minutes during live games.

---

## Decision object

Used everywhere. Defined once here.

```json
{
  "id": "401752794101849903",
  "game_id": "401628201",
  "season": 2026,
  "week": 3,
  "season_type": "regular",
  "source": "cfbd",
  "offense": { "id": "2509", "name": "Purdue", "abbreviation": "PUR", "conference": "Big Ten", "logo_url": "https://...", "color": "#CEB888" },
  "defense": { "id": "127", "name": "Michigan State", "abbreviation": "MSU", "conference": "Big Ten", "logo_url": "https://...", "color": "#18453B" },
  "period": 4,
  "clock": "6:12",
  "down": 4,
  "distance": 2,
  "yard_line": 38,
  "yards_to_goal": 38,
  "offense_score": 17,
  "defense_score": 21,
  "recommendation": "go",
  "decision": "punt",
  "confidence": "clear",
  "margin": 0.094,
  "wp_go": 0.412,
  "wp_punt": 0.318,
  "wp_field_goal": 0.301,
  "wp_delta": -0.094,
  "verdict": "mistake",
  "outcome": null,
  "play_type": "Punt",
  "play_text": "Rhys Dakin punt for 41 yds, fair catch by ...",
  "is_live": false,
  "clock_source": "text_snap",
  "timeouts_imputed": false,
  "model_version": "2.0.0"
}
```

`recommendation` and `decision`: `"go" | "punt" | "field_goal"`.

`wp_field_goal` and `wp_punt` are `null` when the option is infeasible (field goal beyond 50 yards to goal, punt inside 30; `docs/grades.md`). The frontend shows "not an option", never a number. `wp_go` is always present.

`confidence`: `"clear"` (margin ≥ 0.05), `"close"` (0.02–0.05), `"toss_up"` (< 0.02), or `"only_option"` when one option is feasible. `margin` is best minus next best, `null` for `only_option`.

Team `conference`, `logo_url` and `color`, and a decision's `week` and `outcome`, may be `null`.

`id` is the source's play id as a string: CFBD's for batch grades (`source: "cfbd"`), ESPN's for live grades (`source: "espn"`). Anchors on the game page are `#play-{id}`. When a live grade is replaced by the batch grade, the id changes; `GET /games/:id` returns `play_aliases` (ESPN id → CFBD id) so old anchors still resolve. Live decisions also carry `timeouts_uncertain`.

Data-quality flags:
- `clock_source`: `text_snap` (snap time in the play text), `interpolated` (stale clock reconstructed), or a recorded-clock rule. The UI marks `interpolated` as an estimated clock.
- `timeouts_imputed`: the game never recorded timeouts; typical values were used.
- `model_version`: the win-probability model version the play was graded with.

`outcome` is reserved and currently `null`; `play_type` is the provider's play type. `clock` is `M:SS`.

`verdict` is derived, not stored raw:
- `"correct"` — decision matched recommendation
- `"mistake"` — didn't match, `abs(wp_delta) >= 0.05`
- `"marginal"` — didn't match, `abs(wp_delta) < 0.05`

The 0.05 threshold lives in one place in the backend. Don't hardcode it in the frontend.

---

## Game page

### `GET /games/:game_id`

```json
{
  "data": {
    "game": {
      /* Game summary (see GET /games) */
    },
    "grading": { "status": "graded", "message": null },
    "wp_series": [
      { "period": 1, "clock": "15:00", "seconds_remaining": 3600, "home_wp": 0.52, "play_id": "401752794101849801" }
    ],
    "decisions": [ /* Decision objects, chronological */ ],
    "totals": {
      "home": { "fourth_downs": 4, "wp_delta": 0.012 },
      "away": { "fourth_downs": 6, "wp_delta": -0.141 }
    }
  }
}
```

`wp_series` is the home team's WP before every snap (downs 1–4, regulation), downsampled to about 200 points, always keeping fourth downs so chart markers sit on the line. A final game gets a closing point at `seconds_remaining: 0` with the result (1, 0 or 0.5) and `play_id: null`. Empty for games that aren't graded.

`grading.status` says why a game does or doesn't have grades; `message` is plain language for the page, `null` when graded:

| Status | Meaning |
|---|---|
| `graded` | Graded |
| `no_fourth_downs` | Graded, but no fourth down was in scope |
| `failed_quality_gate` | Play-by-play doesn't reconcile with the final score; not graded |
| `awaiting_plays` | Final, but CFBD hasn't published play-by-play yet |
| `not_final` | Not final |
| `not_processed` | Final and waiting for the next process run |
| `provisional` | Not batch graded yet; `decisions` are live grades from ESPN play-by-play (`source: "espn"`) |

`totals.*.wp_delta` sums that team's decisions (≤ 0).

**Cache:** 30s / 60s CDN until the game leaves the 7-day reprocessing window, then 1h / 24h CDN.

### `GET /games?season=&week=&season_type=regular&team=&conference=`

Index for the games list. Without `season` and `week`, returns the latest week with graded decisions. `team` is a team id.

```json
{
  "data": {
    "season": 2026, "week": 2, "season_type": "regular",
    "games": [
      {
        "id": "401856784", "season": 2026, "week": 2, "season_type": "regular",
        "start_date": "2026-09-13T00:08:00Z", "status": "final", "neutral_site": false,
        "home": { /* team */ }, "away": { /* team */ },
        "home_score": 44, "away_score": 3,
        "grading_status": "graded", "fourth_downs": 17, "wp_lost": 0.0033
      }
    ]
  }
}
```

`status`: `final | scheduled | in_progress`. `wp_lost` is positive: WP surrendered by both teams on calls that didn't match the model.

---

## Week in review

Computed on request from stored grades (`backend/app/api/aggregates.py`), so totals always equal the sum of their games and a regrade updates them immediately. Scope is **FBS offenses** (`scope: "fbs_offenses"`), so counts are lower than `/scoreboard/week`, which includes every graded offense.

### `GET /week-in-review/:season/:week?season_type=regular`
### `GET /week-in-review/latest` — the most recent week whose games are all final.

```json
{
  "data": {
    "season": 2026, "week": 2, "season_type": "regular",
    "is_complete": true,
    "scope": "fbs_offenses",
    "games_total": 86, "games_graded": 82,
    "wp_lost_total": 3.7318,
    "wp_lost_per_game": 0.0455,
    "fourth_downs_total": 856,
    "mistakes": 9,
    "followed_model_rate": 0.56,
    "worst_call": { /* Decision */ },
    "best_call": { /* Decision */ },
    "by_conference": [
      { "conference": "American Athletic", "wp_lost": 0.5353, "fourth_downs": 96, "games": 11,
        "wp_lost_per_game": 0.0487, "followed_model_rate": 0.5625 }
    ],
    "punt_index_movers": [
      { "coach_id": "1234", "coach_name": "Fake Coach", "team": { }, "value": 0.042, "rank_now": 1, "rank_before": 4 }
    ],
    "commentary": null
  }
}
```

- `worst_call`: the decision with the most negative `wp_delta`; `null` if every call matched.
- `best_call`: a call that matched the recommendation, preferring go-for-it decisions, with the largest `margin`.
- `by_conference`: the offense's conference that season, sorted by `wp_lost_per_game` (highest first).
- `punt_index_movers`: coaches whose season-to-date Punt Index rank (WP lost, regular season, at least 3 games) changed most from the previous week. `value` is their WP lost per game now. Empty in week 1, early in a season, and in the postseason.
- `commentary`: optional plain text (paragraphs separated by blank lines), set with `jobs.commentary`. `null` is normal.

`is_complete` is false while games in the week are still unplayed. The page renders partial with a note rather than 404.

**Cache:** 5 min / 1h CDN once complete, 30s / 60s CDN while in progress.

---

## The Punt Index

### `GET /punt-index?subject=coach&metric=wp_lost&season_from=&season_to=&conference=&min_games=6&returning=false`

- `subject`: `coach` | `team`. `metric`: `wp_lost` | `go_rate`.
- `season_to` defaults to the latest season in which some team has `min_games` graded games, and `season_from` defaults to `season_to`.
- `conference` filters on the team's conference in each season.
- `returning=true` (coaches only) keeps coaches with a segment in the current season.

Definitions (FBS offenses only):
- `wp_lost`: conservative WP lost per game. It sums `-wp_delta` over fourth downs where the model recommended `go` and the team kicked or punted, divided by games with a graded fourth down. Ranked highest first.
- `go_rate`: `went_for_it / go_recommendations`. Ranked lowest first.
- Coach credit follows `coach_team_seasons` (`jobs.coaches`). Fourth downs from team-seasons that can't be split reliably are unattributed: counted for teams, not coaches, and reported in `unattributed_fourth_downs`.

```json
{
  "data": {
    "subject": "coach",
    "metric": "wp_lost",
    "season_from": 2025, "season_to": 2025,
    "conference": null,
    "min_games": 6,
    "returning": false,
    "conferences": ["ACC", "American Athletic"],
    "unattributed_fourth_downs": 0,
    "rows": [
      {
        "rank": 1,
        "id": "1234",
        "name": "Fake Coach",
        "team": { /* team: the most recent team in the range */ },
        "value": 0.0711,
        "games": 9,
        "fourth_downs": 104,
        "go_recommendations": 51,
        "went_for_it": 14,
        "wp_lost_total": 0.64,
        "seasons": [2025],
        "sample_warning": false
      }
    ]
  }
}
```

`id` is the CFBD coach id or team id, as a string.

`sample_warning` is true below `min_games`; those rows have `rank: null` and come after the ranked rows. Rows below the threshold are still returned so they can be shown greyed out. Silently dropping them makes the ranking look wrong to anyone checking for their own team.

**Cache:** 5 min / 1h CDN.

### `GET /punt-index/:subject/:id`

Season-by-season rows for one coach or team:

```json
{
  "data": {
    "subject": "coach", "id": "1234", "name": "Fake Coach",
    "interim_seasons": [2021],
    "seasons": [
      { "season": 2025, "team": { }, "games": 9, "fourth_downs": 104, "go_recommendations": 51,
        "went_for_it": 14, "go_rate": 0.2745, "wp_lost": 0.0711, "wp_lost_total": 0.64,
        "rank": 1, "ranked_of": 126 }
    ]
  }
}
```

`rank` is by WP lost per game that season, among subjects with at least 6 graded games. `interim_seasons` lists seasons the coach took over mid-season.

---

## Simulator

### `GET /simulate?distance=&yards_to_goal=&period=&clock=&offense_score=&defense_score=&offense_timeouts=3&defense_timeouts=3&spread=0&home=neutral`

Runs the grading option evaluator on one state, about 70 ms warm, memoized per model version (`backend/app/api/simulate.py`). There's no precomputed table: the models take about 25 inputs, and a table would have to fix most of them.

| Param | Range | Notes |
|---|---|---|
| `distance` | 1–99 | ≤ `yards_to_goal` (equal means 4th & goal) |
| `yards_to_goal` | 1–99 | from the offense's perspective |
| `period` | 1–4 | overtime isn't modeled |
| `clock` | `M:SS`, 0:00–15:00 | clock left in the period |
| `offense_score`, `defense_score` | 0–150 | both, not a differential: the WP model uses each score |
| `offense_timeouts`, `defense_timeouts` | 0–3 | default 3 |
| `spread` | −50–50 | offense's point spread, negative = favored; rounded to 0.5 |
| `home` | `home` \| `away` \| `neutral` | default `neutral` |

`spread` replaces the earlier `offense_rating`/`defense_rating`. It's mapped to both Elo ratings by inverting the spread imputer around the FBS base rating, so one number carries team strength consistently for all four models. Weather, elevation and indoors use the documented defaults, which are echoed in `defaults`.

```json
{
  "data": {
    "recommendation": "go",
    "confidence": "clear",
    "margin": 0.0716,
    "wp_go": 0.3333, "wp_field_goal": 0.2618, "wp_punt": 0.247,
    "p_convert": 0.5666, "p_fg_make": 0.4486, "punt_opponent_yards_to_goal": 87.6,
    "inputs": { "distance": 2, "yards_to_goal": 40, "offense_score": 17, "defense_score": 21, "period": 4,
                "clock_seconds": 360, "offense_timeouts": 3, "defense_timeouts": 3, "spread": 0.0,
                "home": "neutral", "offense_elo": 1495.3, "defense_elo": 1504.7 },
    "defaults": { "fbs_base_elo": 1500.0, "temperature": 68.4, "wind_speed": 7.0, "precipitation": 0.0,
                  "elevation_m": 185.4, "indoors": false, "season": 2026 },
    "model_versions": { "win_probability": "2.0.0" },
    "historical": {
      "similar_situations": 41,
      "went_for_it": 0.9512, "punted": 0.0488, "kicked_field_goal": 0.0, "model_said_go": 0.9756,
      "conversion_rate": null,
      "criteria": { "distance": [2, 2], "yards_to_goal": [35, 45], "score_diff": [-8, -4], "period": 4,
                    "scope": "FBS offenses, 2013 on" },
      "examples": [ /* up to 5 Decision objects, most recent first */ ]
    }
  },
  "meta": { "generated_at": "...", "stale": false, "source": "model" }
}
```

- `confidence`: `"clear"` (margin ≥ 0.05), `"close"` (0.02–0.05), `"toss_up"` (< 0.02) or `"only_option"`. Infeasible options are `null`, as in the Decision object.
- `historical`: graded fourth downs with the same distance (±1 from 4–9, 10+ pooled), yards to goal ±5, the same score band (tied, 1–3, 4–8, 9+ either way) and the same quarter. It describes what coaches did and isn't a model input. `conversion_rate` stays `null` until conversion outcomes are stored with grades.
- Errors: `400 BAD_PARAMS` for out-of-range values, a malformed clock, or `distance` > `yards_to_goal`.

**Cache:** `public, max-age=3600, s-maxage=86400`; the same inputs and model version always give the same answer.

---

## Support

### `GET /teams?classification=` — all teams (CFBD `/teams`) with logo URLs and colors, keyed by team id. Cache 7d.
### `GET /health` — no envelope.

```json
{
  "status": "ok",
  "model_versions": { "win_probability": "2.0.0", "conversion": "2.0.0", "field_goal": "2.0.0", "punt": "2.0.0", "decision_assumptions": "2.0.0" },
  "mistake_threshold": 0.05,
  "last_runs": { "game_check": { "run_id": "...", "status": "ok", "started_at": "...", "finished_at": "..." }, "process": { }, "pregame_snapshot": { }, "teams": { }, "backfill": { } },
  "games_processed_24h": 171,
  "stale": false,
  "scheduler_enabled": true,
  "ticker_updated_at": "2026-09-13T04:52:56Z"
}
```

`stale` (here and in every envelope) is true when a final game from the last 7 days has gone 18 hours without being graded or ruled out by the quality gate.

---

## Errors

```json
{
  "error": { "code": "GAME_NOT_FOUND", "message": "No game with that id." }
}
```

`400` bad params, `404` not found, `503` pipeline cold with no cached data. Never `500` a user-facing page — degrade to stale data first.

Messages are plain language. They may be shown to users directly.
