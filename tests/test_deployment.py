"""The secrets of the gateway must not reach the repository or the image.

The env file holds the key of the model gateway. It is ignored by git and
excluded from the build context, and the container mounts it read-only
instead of baking it into a layer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def gitignore() -> list[str]:
    return [
        line.strip()
        for line in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    ]


@pytest.fixture(scope="module")
def dockerignore() -> list[str]:
    return [
        line.strip()
        for line in (PROJECT_ROOT / ".dockerignore")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


@pytest.fixture(scope="module")
def compose() -> str:
    return (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_the_env_file_is_ignored_by_git(gitignore):
    assert ".env" in gitignore


def test_the_template_of_the_env_file_is_tracked(gitignore):
    assert "!.env.example" in gitignore


def test_the_env_file_is_out_of_the_build_context(dockerignore):
    assert ".env" in dockerignore


def test_the_image_does_not_copy_the_env_file(dockerfile):
    for line in dockerfile.splitlines():
        if line.strip().startswith("COPY"):
            assert ".env" not in line


def test_the_env_file_is_mounted_and_not_copied(compose):
    assert "./.env:/app/.env:ro" in compose
    assert "build:" in compose


def test_the_store_lives_in_a_volume(compose):
    assert "wacc-data:/data" in compose
    assert "WACC_LAB_DB: /data/wacc_lab.db" in compose


def test_the_container_is_built_from_the_dockerfile(compose):
    assert "build: ." in compose


def test_git_ignores_the_env_file():
    # The file is there, and git does not want to know about it.
    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode == 128:
        pytest.skip("git is not available here")
    assert result.returncode == 0
