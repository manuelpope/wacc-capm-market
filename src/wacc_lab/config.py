"""Runtime configuration, read from the environment.

The environment is filled from the project's ``.env`` file before anything is
read, so the app picks up the credentials of the model gateway without an
export in the shell. A real environment variable always wins over the file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv


def _project_root() -> Path:
    """The root of the app: the env file and the wiki are read from it.

    The source tree is the root when the app runs from it. In an installed
    wheel the package sits in site-packages and there is no repository around
    it, so the working directory is used instead. A container points at its
    own root with ``WACC_LAB_PROJECT_ROOT``.
    """
    explicit = os.environ.get("WACC_LAB_PROJECT_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    here = Path(__file__).resolve()
    candidate = here.parents[2]
    if (candidate / "pyproject.toml").is_file():
        return candidate
    return Path.cwd()


PROJECT_ROOT = _project_root()

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "wacc_lab.db"
DEFAULT_TTL_HOURS = 24.0
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_LLM_MODEL = "qwen3.5:9b-mlx"
STATIC_DIR = Path(__file__).resolve().parent / "static"
# The HTML wiki. It lives in the repository, so it is not part of the wheel,
# and the mount is skipped when it is not there.
WIKI_DIR = PROJECT_ROOT / "docs"

# The gateway credentials file uses short, generic names. They are read as
# aliases of the canonical variables, and a canonical variable always wins.
LLM_ALIASES: dict[str, str] = {
    "url": "WACC_LAB_LLM_BASE_URL",
    "model": "WACC_LAB_LLM_MODEL",
    "user": "WACC_LAB_LLM_USER",
    "MMX-API-KEY_VIRTUAL": "WACC_LAB_LLM_API_KEY",
}

# The same map read the other way, from a canonical name to its alias.
_ALIAS_OF: dict[str, str] = {canonical: alias for alias, canonical in LLM_ALIASES.items()}

# The value of the reasoning effort that leaves the field out of the request.
# A reasoning model that requires its own thinking rejects "none", so the
# field is sent only when the server understands it.
REASONING_EFFORT_OMIT = "omit"


def env_file_candidates() -> list[Path]:
    """The places an env file is looked for, in order."""
    explicit = os.environ.get("WACC_LAB_ENV_FILE")
    if explicit:
        return [Path(explicit).expanduser()]
    return [PROJECT_ROOT / ".env", Path.cwd() / ".env"]


def env_file_path() -> Path | None:
    """The env file the app reads, if there is one."""
    for candidate in env_file_candidates():
        if candidate.is_file():
            return candidate
    return None


def load_env() -> bool:
    """Fill the environment from the project's env file.

    The file is optional. A value the environment already holds is left
    alone: the file fills the gaps, it does not overwrite what the shell
    says.
    """
    path = env_file_path()
    if path is None:
        return False
    return bool(load_dotenv(path, override=False))


def _aliased(canonical: str) -> str | None:
    """The canonical variable, or its alias when the canonical one is unset."""
    value = os.environ.get(canonical)
    if value:
        return value
    alias = _ALIAS_OF.get(canonical)
    if alias:
        return os.environ.get(alias) or None
    return None


def normalize_base_url(url: str) -> str:
    """Give the base URL the versioned path the client expects.

    The client appends ``/chat/completions`` to the base URL, so a URL that
    carries only a host and a port needs the ``/v1`` prefix of the
    OpenAI-compatible API. A URL that already names a path is left alone.
    """
    cleaned = url.strip()
    parts = urlsplit(cleaned)
    if not parts.scheme or not parts.netloc:
        return cleaned
    path = parts.path.rstrip("/")
    if not path:
        path = "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _reasoning_effort() -> str | None:
    """The reasoning effort to send, or ``None`` to leave it out."""
    raw = os.environ.get("WACC_LAB_LLM_REASONING_EFFORT")
    if raw is None:
        return "none"
    value = raw.strip()
    if not value or value.lower() == REASONING_EFFORT_OMIT:
        return None
    return value


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool = True
    base_url: str = DEFAULT_LLM_BASE_URL
    model: str = DEFAULT_LLM_MODEL
    api_key: str | None = None
    timeout: float = 180.0
    mode: str = "chat"
    user: str | None = None
    reasoning_effort: str | None = "none"

    @classmethod
    def from_env(cls) -> LLMSettings:
        load_env()
        enabled_raw = os.environ.get("WACC_LAB_LLM_ENABLED")
        enabled = enabled_raw.strip().lower() not in {"0", "false", "no", "off"} if enabled_raw else True
        timeout_raw = os.environ.get("WACC_LAB_LLM_TIMEOUT")
        try:
            timeout = float(timeout_raw) if timeout_raw else 180.0
        except ValueError:
            timeout = 180.0
        base_url = _aliased("WACC_LAB_LLM_BASE_URL")
        model = _aliased("WACC_LAB_LLM_MODEL")
        return cls(
            enabled=enabled,
            base_url=normalize_base_url(base_url or DEFAULT_LLM_BASE_URL),
            model=model or DEFAULT_LLM_MODEL,
            api_key=_aliased("WACC_LAB_LLM_API_KEY"),
            timeout=timeout,
            mode=os.environ.get("WACC_LAB_LLM_MODE", "chat"),
            user=_aliased("WACC_LAB_LLM_USER"),
            reasoning_effort=_reasoning_effort(),
        )


@dataclass(frozen=True)
class Settings:
    db_path: Path = DEFAULT_DB_PATH
    ttl_hours: float = DEFAULT_TTL_HOURS
    news_ttl_hours: float = 6.0
    news_limit: int = 8
    llm: LLMSettings = LLMSettings()
    env_file: Path | None = None

    @classmethod
    def from_env(cls) -> Settings:
        load_env()
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
            env_file=env_file_path(),
        )
