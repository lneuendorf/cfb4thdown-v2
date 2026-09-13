---
description: Run the data pipeline locally for a given week and report what changed
argument-hint: [season] [week]
allowed-tools: Bash, Read, Grep
---

Run the pipeline locally for season $1, week $2.

1. Confirm `CFBD_API_KEY` is set. If not, stop and say so.
2. Run `cd backend && uv run python -m jobs.game_check` and report what it found.
3. If there's anything to process, run `uv run python -m jobs.process --season $1 --week $2`.
4. Read the resulting run_log entry and report: games fetched, games reprocessed, decisions graded, exclusions by reason, validation flags, errors.
5. Flag anything that looks off — fourth downs per game outside 2-20, aggregate WP shifting more than 20% against the previous run on settled data, any unattributed coach records.

Don't fix problems you find. Report them.
