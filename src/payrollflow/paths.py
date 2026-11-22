"""Centralized project paths; no machine-specific absolute paths."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
SAMPLE_DATA_DIR = DATA_DIR / "sample"
INPUT_DATA_DIR = DATA_DIR / "input"
HISTORY_DATA_DIR = DATA_DIR / "history"
DATABASE_DIR = DATA_DIR / "database"
OUTPUT_DIR = PROJECT_ROOT / "output"
LOG_DIR = PROJECT_ROOT / "logs"


def ensure_runtime_directories() -> None:
    """Create local runtime directories when the application starts."""
    for directory in (INPUT_DATA_DIR, HISTORY_DATA_DIR, DATABASE_DIR, OUTPUT_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
