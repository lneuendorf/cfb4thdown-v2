---
description: Run the full check suite across both halves of the repo
allowed-tools: Bash, Read
---

Run every check and report a single consolidated result.

Frontend:
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`

Backend:
- `cd backend && uv run ruff check .`
- `cd backend && uv run pytest -q`

Report pass or fail per check. For failures, show the relevant error and say what's needed to fix it — don't fix anything unless asked.

If a command doesn't exist yet because that half isn't scaffolded, say so rather than treating it as a failure.
