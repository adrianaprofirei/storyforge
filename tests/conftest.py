"""Shared fixtures. Every test session works in its own temporary data folder, so tests never touch
your projects; the demo series is created there once (offline, no API keys needed)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

# Isolate the session before storyforge reads its settings: own data dir, offline providers.
_SESSION_DATA = Path(os.environ.get("STORYFORGE_TEST_DATA", "")) if os.environ.get("STORYFORGE_TEST_DATA") else None


def pytest_configure(config):
    global _SESSION_DATA
    if _SESSION_DATA is None:
        import tempfile

        _SESSION_DATA = Path(tempfile.mkdtemp(prefix="storyforge_test_"))
    os.environ["STORYFORGE_DATA_DIR"] = str(_SESSION_DATA)
    os.environ["STORYFORGE_DEMO"] = "1"           # never call paid LLM APIs from tests
    os.environ.setdefault("TTS_PROVIDER", "auto")  # piper/espeak if installed, else silent
    # empty values win over .env (python-dotenv never overrides variables that are already set), so
    # keys in your .env can't make tests call paid APIs
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"):
        os.environ[key] = ""
    from storyforge.config import reset_settings

    reset_settings()


def pytest_unconfigure(config):
    if _SESSION_DATA and not os.environ.get("STORYFORGE_TEST_DATA") and not os.environ.get("STORYFORGE_KEEP_TEST_DATA"):
        shutil.rmtree(_SESSION_DATA, ignore_errors=True)


@pytest.fixture(scope="session")
def settings():
    from storyforge.config import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def demo_project(settings):
    from storyforge.project import Project

    return Project.ensure_demo()


@pytest.fixture()
def fresh_project(settings, tmp_path_factory):
    """A throw-away copy of the demo series under a unique id (safe to mutate)."""
    import uuid

    from storyforge.config import ASSETS_DIR
    from storyforge.project import Project
    from storyforge.util.io import read_yaml

    bible = read_yaml(ASSETS_DIR / "samples" / "bible.yaml")
    sid = f"t_{uuid.uuid4().hex[:8]}"
    bible.update({"series_id": sid, "arcs": [], "episodes": [], "continuity_log": []})
    cast = read_yaml(ASSETS_DIR / "samples" / "cast.yaml")
    p = Project.create(bible, cast)
    yield p
    shutil.rmtree(p.root, ignore_errors=True)


def blender_skip_reason(settings) -> str | None:
    if settings.blender_command() is None:
        return ("Blender not available: set BLENDER_PATH (blender executable) or BLENDER_PYTHON (a Python with the "
                "`bpy` module) in .env to run render tests")
    return None


def ffmpeg_skip_reason(settings) -> str | None:
    if not settings.tool("ffmpeg"):
        return "ffmpeg not found on PATH (or FFMPEG_PATH); install ffmpeg to run encode/loudness-on-MP4 tests"
    return None


@pytest.fixture(scope="session")
def require_blender(settings):
    reason = blender_skip_reason(settings)
    if reason:
        pytest.skip(reason)


@pytest.fixture(scope="session")
def require_ffmpeg(settings):
    reason = ffmpeg_skip_reason(settings)
    if reason:
        pytest.skip(reason)
