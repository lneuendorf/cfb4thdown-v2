"""Paths and scope constants shared by ingestion, dataset building, and training."""

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = BACKEND_DIR / "modeling" / "reports"
ARTIFACTS_DIR = BACKEND_DIR / "modeling" / "artifacts"

# Seasons with play-by-play used for model training.
TRAIN_SEASONS = range(2013, 2026)
# Elo is replayed from here so 2013 ratings have a long burn-in.
ELO_FIRST_SEASON = 2000

# Only games with at least one FBS team are in scope.
IN_SCOPE_CLASSIFICATION = "fbs"
SEASON_TYPES = ("regular", "postseason")

# Temporal split for model evaluation. Final artifacts are refit on all TRAIN_SEASONS.
VALID_SEASONS = (2022, 2023)
TEST_SEASONS = (2024, 2025)

RANDOM_SEED = 20260912
