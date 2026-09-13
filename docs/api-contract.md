# API contract

Base: `/api/v1`. JSON only. No authentication. Interactive docs at `/api/v1/docs`.

Implemented in `backend/app/api/` (Phase 2): `/scoreboard/latest`, `/scoreboard/week`, `/games`, `/games/:id`, `/teams`, `/ticker`, `/health`. The rest of this document is specified but not built yet.

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

`/scoreboard/live` arrives with live grading (`docs/roadmap.md` Phase 6). Until then the home page uses `/scoreboard/latest`.

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

`id` is the source's play id as a string: CFBD's for batch grades (`source: "cfbd"`), ESPN's for live grades (`source: "espn"`). Anchors on the game page are `#play-{id}`. When a live grade is replaced by the batch grade (Phase 6), the id changes; the live-to-batch mapping will keep old anchors resolvable.

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

### `GET /week-in-review/:season/:week`

```json
{
  "data": {
    "season": 2026, "week": 3,
    "is_complete": true,
    "wp_lost_total": 1.84,
    "fourth_downs_total": 412,
    "followed_model_rate": 0.61,
    "worst_call": { /* Decision */ },
    "best_call": { /* Decision */ },
    "by_conference": [
      { "conference": "Big Ten", "wp_lost": 0.31, "fourth_downs": 58, "followed_model_rate": 0.58 }
    ],
    "punt_index_movers": [
      { "coach_id": "...", "coach_name": "Barry Odom", "team": { }, "change": 0.042, "rank_now": 1, "rank_before": 4 }
    ],
    "commentary": null
  }
}
```

`is_complete` is false while games in the week are still unplayed. The page should render partial with a note rather than 404.

`commentary` is an optional markdown string, manually added. Null is normal.

**Cache:** 24h once complete, 1h while in progress.

---

## The Punt Index

### `GET /punt-index?subject=coach&metric=wp_lost&season_from=&season_to=&conference=&min_games=`

`subject`: `coach` | `team`. `metric`: `wp_lost` | `go_rate`.

```json
{
  "data": {
    "subject": "coach",
    "metric": "wp_lost",
    "season_from": 2026, "season_to": 2026,
    "min_games": 6,
    "rows": [
      {
        "rank": 1,
        "id": "odom-barry",
        "name": "Barry Odom",
        "team": { /* team */ },
        "value": 0.320,
        "games": 12,
        "fourth_downs": 41,
        "sample_warning": false
      }
    ]
  }
}
```

`sample_warning` is true below `min_games`. Rows below the threshold are still returned so they can be shown greyed out — silently dropping them makes the ranking look wrong to anyone checking for their own team.

**Cache:** 12h.

### `GET /punt-index/:subject/:id`

Season-by-season trend for one coach or team.

---

## Simulator

### `GET /simulate?down=4&distance=&yards_to_goal=&score_diff=&period=&clock=&offense_rating=&defense_rating=`

```json
{
  "data": {
    "recommendation": "go",
    "confidence": "clear",
    "wp_go": 0.412,
    "wp_punt": 0.318,
    "wp_field_goal": 0.301,
    "margin": 0.094,
    "historical": {
      "similar_situations": 47,
      "went_for_it": 0.22,
      "conversion_rate": 0.58
    }
  }
}
```

`confidence`: `"clear"` (margin ≥ 0.05), `"close"` (0.02-0.05), `"toss_up"` (< 0.02), `"only_option"`. Infeasible options are `null`, as in the Decision object.

**Cache:** indefinitely — same inputs always give the same answer for a given model version. Key the cache on model version so a retrain invalidates it.

### `GET /simulate/table`

Precomputed lookup covering the common input space, for client-side evaluation. Gzipped JSON, versioned filename, cached forever by the CDN. If this ships, the simulator page never calls `/simulate` at all.

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
