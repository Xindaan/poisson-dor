from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
EXPORTS_DIR = PROJECT_ROOT / "exports"
ASSETS_DIR = PROJECT_ROOT / "assets"


def ensure_dirs() -> None:
    for path in (DATA_DIR, RAW_DIR, EXPORTS_DIR, ASSETS_DIR):
        path.mkdir(parents=True, exist_ok=True)
