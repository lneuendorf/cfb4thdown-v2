# API + in-process scheduler (app.scheduler). One worker: the scheduler and SQLite writes
# must live in a single process. Mount a volume at /data holding cfb4thdown.db.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-group train
COPY app ./app
COPY jobs ./jobs
COPY modeling ./modeling
COPY providers ./providers

ENV CFB4THDOWN_DB=/data/cfb4thdown.db \
    SCHEDULER_ENABLED=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
# Railway (and most hosts) inject PORT; default to 8000 locally.
CMD ["sh", "-c", "uv run --no-sync uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
