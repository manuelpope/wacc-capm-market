"""Runtime configuration, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "wacc_lab.db"
DEFAULT_TTL_HOURS = 24.0
STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class Settings:
    db_path: Path = DEFAULT_DB_PATH
    ttl_hours: float = DEFAULT_TTL_HOURS

    @classmethod
    def from_env(cls) -> "Settings":
        db_path = Path(os.environ.get("WACC_LAB_DB", str(DEFAULT_DB_PATH)))
        ttl_raw = os.environ.get("WACC_LAB_TTL_HOURS")
        try:
            ttl_hours = float(ttl_raw) if ttl_raw else DEFAULT_TTL_HOURS
        except ValueError:
            ttl_hours = DEFAULT_TTL_HOURS
        return cls(db_path=db_path, ttl_hours=ttl_hours)
