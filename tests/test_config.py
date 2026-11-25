"""Tests for the env file and the configuration it feeds."""

from __future__ import annotations

import os

import pytest

from wacc_lab.config import (
    REASONING_EFFORT_OMIT,
    LLMSettings,
    Settings,
    env_file_candidates,
    load_env,
    normalize_base_url,
)


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """An isolated environment with an env file of its own.

    The file the repository ships is never read by the tests: the variable
    that points at the env file is set to a path in a temporary directory.
    """
    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv("WACC_LAB_ENV_FILE", str(path))
    before = dict(os.environ)
    try:
        yield path
    finally:
        os.environ.clear()
        os.environ.update(before)


# ----------------------------------------------------------------- the loading


def test_the_file_fills_the_environment(env_file):
    env_file.write_text("WACC_LAB_LLM_MODEL=from-the-file\n", encoding="utf-8")
    os.environ.pop("WACC_LAB_LLM_MODEL", None)

    load_env()

    assert os.environ["WACC_LAB_LLM_MODEL"] == "from-the-file"


def test_the_environment_wins_over_the_file(env_file):
    env_file.write_text("WACC_LAB_LLM_MODEL=from-the-file\n", encoding="utf-8")
    os.environ["WACC_LAB_LLM_MODEL"] = "from-the-shell"

    load_env()

    assert os.environ["WACC_LAB_LLM_MODEL"] == "from-the-shell"


def test_a_missing_file_is_not_an_error(env_file):
    env_file.unlink()

    assert load_env() is False


def test_the_file_is_optional(env_file):
    # No file, and the app still has its defaults.
    env_file.unlink()
    os.environ.pop("WACC_LAB_LLM_MODEL", None)

    assert LLMSettings.from_env().model == "qwen3.5:9b-mlx"


def test_the_file_that_is_read_can_be_chosen(env_file):
    other = env_file.parent / "other.env"
    other.write_text("WACC_LAB_LLM_MODEL=from-the-other\n", encoding="utf-8")
    os.environ["WACC_LAB_ENV_FILE"] = str(other)
    os.environ.pop("WACC_LAB_LLM_MODEL", None)

    load_env()

    assert os.environ["WACC_LAB_LLM_MODEL"] == "from-the-other"


def test_the_file_is_looked_for_next_to_the_app(env_file):
    # Without the variable that points at it, the file next to the app is
    # the one that is read.
    os.environ.pop("WACC_LAB_ENV_FILE", None)

    candidates = env_file_candidates()

    assert candidates[0].name == ".env"


# ------------------------------------------------------------------ the aliases


def test_the_short_names_are_read_as_aliases(env_file):
    env_file.write_text(
        "MMX-API-KEY_VIRTUAL=sk-secret\n"
        "url=http://matb.server.home.arpa:4000\n"
        "user=LLMWACC\n"
        "model=MiniMax-M3.1-Flash\n",
        encoding="utf-8",
    )
    for name in (
        "WACC_LAB_LLM_BASE_URL",
        "WACC_LAB_LLM_API_KEY",
        "WACC_LAB_LLM_USER",
        "WACC_LAB_LLM_MODEL",
    ):
        os.environ.pop(name, None)

    llm = LLMSettings.from_env()

    assert llm.base_url == "http://matb.server.home.arpa:4000/v1"
    assert llm.api_key == "sk-secret"
    assert llm.user == "LLMWACC"
    assert llm.model == "MiniMax-M3.1-Flash"


def test_the_canonical_name_wins_over_the_alias(env_file):
    env_file.write_text("url=http://from-the-alias:4000\n", encoding="utf-8")
    os.environ["WACC_LAB_LLM_BASE_URL"] = "http://from-the-canonical:4000/v1"

    llm = LLMSettings.from_env()

    assert llm.base_url == "http://from-the-canonical:4000/v1"


def test_a_value_of_the_file_is_read_when_the_shell_is_silent(env_file):
    env_file.write_text("WACC_LAB_LLM_MODEL=from-the-file\n", encoding="utf-8")
    os.environ.pop("WACC_LAB_LLM_MODEL", None)

    llm = LLMSettings.from_env()

    assert llm.model == "from-the-file"


# ------------------------------------------------------------- the base URL


def test_a_url_without_a_path_gets_the_versioned_one():
    assert normalize_base_url("http://matb.server.home.arpa:4000") == (
        "http://matb.server.home.arpa:4000/v1"
    )


def test_a_url_with_a_path_is_left_alone():
    assert normalize_base_url("http://127.0.0.1:11434/v1") == (
        "http://127.0.0.1:11434/v1"
    )


def test_the_trailing_slash_is_removed():
    assert normalize_base_url("http://127.0.0.1:11434/v1/") == (
        "http://127.0.0.1:11434/v1"
    )


def test_a_url_without_a_scheme_is_left_alone():
    assert normalize_base_url("127.0.0.1:11434") == "127.0.0.1:11434"


# ------------------------------------------------------- the reasoning effort


def test_the_reasoning_effort_is_asked_for_by_default(env_file):
    os.environ.pop("WACC_LAB_LLM_REASONING_EFFORT", None)
    assert LLMSettings.from_env().reasoning_effort == "none"


def test_the_reasoning_effort_can_be_left_out(env_file):
    os.environ["WACC_LAB_LLM_REASONING_EFFORT"] = REASONING_EFFORT_OMIT
    assert LLMSettings.from_env().reasoning_effort is None


def test_an_empty_reasoning_effort_leaves_the_field_out(env_file):
    os.environ["WACC_LAB_LLM_REASONING_EFFORT"] = ""
    assert LLMSettings.from_env().reasoning_effort is None


# ------------------------------------------------------------------- the settings


def test_the_env_file_is_reported(env_file):
    env_file.write_text("WACC_LAB_TTL_HOURS=1\n", encoding="utf-8")

    settings = Settings.from_env()

    assert settings.env_file == env_file
    assert settings.ttl_hours == 1.0
