# Automation

The old site was run by hand every week. Nothing here runs by hand.

**Where jobs run.** Jobs run inside the API service, as an in-process scheduler (`backend/app/scheduler.py`, enabled with `SCHEDULER_ENABLED=1`). They are not GitHub Actions cron jobs.

The earlier plan (Actions cron dispatching `process` and `live-poll`) doesn't work with SQLite: the database lives on the API host's disk, and Actions runners can't write to it. GitHub Actions runs CI only (`.github/workflows/ci.yml`).

Every job is also a CLI module, so it can be run by hand or from any other scheduler:

```bash
cd backend
uv run python -m jobs.game_check
uv run python -m jobs.process --season 2026 [--reprocess-window] [--game-ids ...]
uv run python -m jobs.pregame_snapshot --season 2026 --hours-ahead 3 --include-started
uv run python -m jobs.teams
uv run python -m jobs.backfill --from 2013 --to 2025
```

---

## Jobs

### `game_check`: hourly, at minute 5

Cheap. Decides whether anything else needs to run.

1. Fetch ESPN's FBS scoreboard for the last 8 days through tomorrow. That's one ESPN request and no CFBD calls.
2. Compare with the database:
   - **new finals:** final games without a `graded` or `failed_quality_gate` row in `game_sources`. Games marked `awaiting_plays` are retried at most every 2 hours.
   - **live:** any game in progress.
   - **pregame due:** a kickoff within 3 hours that has no snapshot taken in the 12 hours before it.
   - **reprocess due:** the daily slot at 10:00 UTC, when there are final games inside the 7-day window.
3. Output: `season`, `has_new_games`, `has_live_games`, `pregame_due`, `reprocess_due`, `new_game_ids`. These are also written to `$GITHUB_OUTPUT` when set.

It is logged in `run_log` like every other job and runs in well under a second.

### `process`: when `game_check` reports new finals or the daily reprocess

Does the real work: fetch, build, grade, and replace rows per game.

1. **Games:** fetch CFBD games for the season (2 calls) into timestamped snapshots, and upsert `games`.
2. **Targets:** final games not yet graded. The daily run also re-checks every final in the 7-day reprocessing window.
3. **Play-by-play:** fetch once per affected (season type, week), 1 call each.
4. **Hash check:** hash each game's plays. An unchanged hash is skipped; a changed one is regraded, which is how corrections are caught.
5. **Pregame context:** games without a pregame snapshot get one first (4 calls). This happens when the job wasn't running before kickoff; see "Retroactive snapshots" below.
6. **Grade:** build pre-snap states and grade fourth downs and the WP series with the backfill's code (`app/batch.py`). That game's `plays_fourth_down`, `exclusions` and `wp_series` rows are replaced in one transaction.

Each game's outcome is recorded in `game_sources.status`: `graded`, `failed_quality_gate` or `awaiting_plays`.

Measured on 2026-09-13: the first run for the 2026 season graded 177 games in 12 seconds using 8 CFBD calls. Re-running with the window found 82 unchanged games in 7 seconds using 4 calls.

### `pregame_snapshot`: when `game_check` reports a kickoff within 3 hours

Freezes Elo, the closing spread, the weather forecast and the venue for games about to start. Live inference and `process` read these snapshots, and the job costs 6 CFBD calls.

Elo history and venues come from the database (`app/reference.py`), which `backfill` fills, so the server doesn't need the raw CFBD cache.

**Retroactive snapshots.** A game graded without a snapshot taken before kickoff gets one at processing time. Its closing line and weather are still correct (CFBD keeps them). Its Elo excludes the game itself, because ratings replay only games that kicked off earlier.

### `teams`: Mondays at 09:00 UTC

Refreshes names, abbreviations, conferences, colors and logos from CFBD `/teams`. One call.

### Ticker: every 30 seconds while games are live, every 10 minutes otherwise

Fetches ESPN's scoreboard for `GET /ticker` and holds it in memory. It is score-only and isn't written to the raw store, because nothing is graded from it.

### `live_poll`: Phase 6

It exists as a CLI (`jobs.live_poll --loop`) but isn't scheduled yet. When live grading ships (`docs/roadmap.md` Phase 6), it joins the scheduler as a third loop, active only while games are live.

### `coaches`: Mondays at 09:00 UTC, after `teams`

Rebuilds coach attribution from CFBD `/coaches` (one call; `jobs/coaches.py`). It also runs on the first hourly check if no attribution exists yet, e.g. on a freshly seeded server.

### Week in Review and the Punt Index: no job

Both are computed on request from stored grades (`app/api/aggregates.py`). There is no Tuesday job; a week becomes the latest Week in Review as soon as all its games are final. Commentary is set by hand with `jobs.commentary`.

### `backfill`: manual only

It regrades history from processed data after a model change, never on a schedule. It also writes every game since 2000 and the venue table, which Elo replay and pregame snapshots need.

---

## Budget

| Source | Use | Measured cost |
|---|---|---|
| CFBD (Tier 1: 5,000 calls/month) | `process` | 2 calls + 1 per affected week, + 4 when snapshots are missing |
| | `pregame_snapshot` | 6 per run |
| | `teams` | 1 per week |
| | `coaches` | 1 per week |
| ESPN (undocumented, no key) | `game_check` | 24 requests/day |
| | ticker | 120 requests/hour while games are live |

**A typical in-season week** is about 350–500 CFBD calls:
- about 15 `process` runs on a Saturday and Sunday at 3–4 calls each;
- 7 daily reprocess runs at about 4 calls;
- 10–20 pregame snapshot runs at 6 calls.

That fits Tier 1 comfortably. The free tier (1,000 calls/month) would be tight in season. `x-calllimit-remaining` is logged on every call and recorded in `run_log`.

---

## Deployment

Step-by-step setup is in `docs/deploy.md`.

`backend/Dockerfile` runs the API and scheduler as one process, with one worker. SQLite writes and the in-memory ticker require a single process.

- **Volume:** mount one at `/data` holding `cfb4thdown.db`.
- **Seeding:** seed it from a local `jobs.backfill` run. The database isn't in git.
- **Frontend:** served by Vercel, with `VITE_API_BASE` pointing at the API host.

| Variable | Where | Purpose |
|---|---|---|
| `CFBD_API_KEY` | API host | CollegeFootballData |
| `CFB4THDOWN_DB` | API host | SQLite path (image default `/data/cfb4thdown.db`) |
| `SCHEDULER_ENABLED` | API host | `1` to run jobs in-process (image default) |
| `CORS_ORIGINS` | API host | The frontend origin(s) |
| `VITE_API_BASE` | Vercel | API origin, e.g. `https://api.cfb4thdown.com` |

Set these in the host's settings, never in the codebase or a log line.

---

## Failure handling

- **A job fails.** It's recorded in `run_log` with its error, and the scheduler keeps going. A failed `process` leaves games unmarked, so the next hourly check retries them.
- **The pipeline falls behind.** The API sets `stale: true` when a final game from the last 7 days has gone 18 hours without being graded. The site keeps working, quietly out of date.
- **Bad data ships.** `run_log` records every run; roll back by rerunning `process --game-ids` (or `backfill`) with the previous model version.
- **ESPN is down or blocked.** The ticker goes stale and `game_check` fails. `process` can still be run by hand with `--season`, because CFBD is independent of ESPN.

---

## Health

`GET /api/v1/health` returns:
- model versions;
- the last run of each job;
- games processed in the last 24 hours;
- the `stale` flag;
- whether the scheduler is enabled;
- the ticker's last refresh.

Point an uptime monitor at it. Alert if `last_runs.game_check.started_at` is more than 2 hours old in season, or `stale` is true.
