"""Runtime configuration, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "wacc_lab.db"
DEFAULT_TTL_HOURS = 24.0
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_LLM_MODEL = "qwen3.5:9b-mlx"
STATIC_DIR = Path(__file__).resolve().parent / "static"
# The HTML wiki. It lives in the repository, so it is not part of the wheel,
# and the mount is skipped when it is not there.
WIKI_DIR = PROJECT_ROOT / "docs"


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool = True
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = DEFAULT_LLM_MODEL
    api_key: str | None = None
    timeout: float = 180.0
    mode: str = "chat"

    @classmethod
    def from_env(cls) -> "LLMSettings":
        enabled_raw = os.environ.get("WACC_LAB_LLM_ENABLED")
        enabled = enabled_raw.strip().lower() not in {"0", "false", "no", "off"} if enabled_raw else True
        timeout_raw = os.environ.get("WACC_LAB_LLM_TIMEOUT")
        try:
            timeout = float(timeout_raw) if timeout_raw else 180.0
        except ValueError:
            timeout = 180.0
        return cls(
            enabled=enabled,
            base_url=os.environ.get("WACC_LAB_LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
            model=os.environ.get("WACC_LAB_LLM_MODEL", DEFAULT_LLM_MODEL),
            api_key=os.environ.get("WACC_LAB_LLM_API_KEY") or None,
            timeout=timeout,
            mode=os.environ.get("WACC_LAB_LLM_MODE", "chat"),
        )


@dataclass(frozen=True)
class Settings:
    db_path: Path = DEFAULT_DB_PATH
    ttl_hours: float = DEFAULT_TTL_HOURS
    news_ttl_hours: float = 6.0
    news_limit: int = 8
    llm: LLMSettings = LLMSettings()

    @classmethod
    def from_env(cls) -> "Settings":
        db_path = Path(os.environ.get("WACC_LAB_DB", str(DEFAULT_DB_PATH)))
        ttl_raw = os.environ.get("WACC_LAB_TTL_HOURS")
        try:
            ttl_hours = float(ttl_raw) if ttl_raw else DEFAULT_TTL_HOURS
        except ValueError:
            ttl_hours = DEFAULT_TTL_HOURS
        news_ttl_raw = os.environ.get("WACC_LAB_NEWS_TTL_HOURS")
        try:
            news_ttl_hours = float(news_ttl_raw) if news_ttl_raw else 6.0
        except ValueError:
            news_ttl_hours = 6.0
        limit_raw = os.environ.get("WACC_LAB_NEWS_LIMIT")
        try:
            news_limit = int(limit_raw) if limit_raw else 8
        except ValueError:
            news_limit = 8
        return cls(
            db_path=db_path,
            ttl_hours=ttl_hours,
            news_ttl_hours=news_ttl_hours,
            news_limit=news_limit,
            llm=LLMSettings.from_env(),
        )
