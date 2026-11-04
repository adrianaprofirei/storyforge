"""Execution context handed to every stage of an episode run."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from storyforge.config import Settings, get_settings
from storyforge.project import Project
from storyforge.util.io import ensure_dir, read_json

log = logging.getLogger("storyforge")


@dataclass
class RunOptions:
    preset: str = "draft"              # draft | final | final_4k | proxy
    force: set[str] = field(default_factory=set)   # stage names to re-run even if cached
    only_shots: list[str] | None = None  # render only these shot ids (others reuse cache)
    until: str | None = None           # stop after this stage
    autofix: bool = True               # apply quality-gate auto fixes and re-run affected stages
    max_frames: int | None = None      # debugging: limit rendered frames per shot
    fps: int | None = None             # override the series fps
    duration_limit: float | None = None  # smoke tests: cut the timeline after N seconds
    skip_render: bool = False


class EpisodeContext:
    def __init__(self, project: Project, episode_id: str, options: RunOptions | None = None,
                 settings: Settings | None = None,
                 on_log: Callable[[str], None] | None = None,
                 on_progress: Callable[[float, str], None] | None = None,
                 cancel_event: threading.Event | None = None):
        self.project = project
        self.episode_id = episode_id
        self.options = options or RunOptions()
        self.settings = settings or get_settings()
        self._on_log = on_log
        self._on_progress = on_progress
        self.cancel_event = cancel_event or threading.Event()
        self.dir = project.episode_dir(episode_id)
        self.stage_name = ""
        self._stage_weight = (0.0, 1.0)
        self._llm = None
        self._tts = None
        self.started = time.time()

    # ------------------------------------------------------------------ paths
    def path(self, *parts: str) -> Path:
        return self.dir.joinpath(*parts)

    def sub(self, *parts: str) -> Path:
        return ensure_dir(self.dir.joinpath(*parts))

    @property
    def cache_root(self) -> Path:
        return ensure_dir(self.settings.data_dir / "cache")

    def global_cache(self, kind: str) -> Path:
        return ensure_dir(self.cache_root / kind)

    # ------------------------------------------------------------------ project data
    def bible(self) -> dict:
        return self.project.bible()

    def cast(self) -> dict[str, dict]:
        return self.project.cast()

    def meta(self) -> dict:
        return self.project.episode_meta(self.episode_id)

    def screenplay(self) -> dict:
        """The final (reviewed + user-edited) screenplay used by all downstream stages."""
        return read_json(self.path("screenplay.final.json"))

    @property
    def fps(self) -> int:
        if self.options.fps:
            return int(self.options.fps)
        fmt = self.bible().get("format", {})
        return int(fmt.get("fps") or self.settings.render_fps or 30)

    def style(self) -> str:
        b = self.bible()
        return (b.get("look", {}) or {}).get("style") or b["world"].get("visual_style", "stylized_3d")

    # ------------------------------------------------------------------ providers
    @property
    def llm(self):
        if self._llm is None:
            from storyforge.providers.llm import get_llm

            self._llm = get_llm(self.settings)
        return self._llm

    @property
    def tts(self):
        if self._tts is None:
            from storyforge.providers.tts import get_tts_chain

            self._tts = get_tts_chain(self.settings)
        return self._tts

    # ------------------------------------------------------------------ reporting
    def log(self, msg: str) -> None:
        line = f"[{self.episode_id}:{self.stage_name or '-'}] {msg}"
        if self._on_log:
            self._on_log(line)
        else:
            log.info(line)

    def progress(self, fraction: float, msg: str = "") -> None:
        lo, hi = self._stage_weight
        overall = lo + (hi - lo) * max(0.0, min(1.0, fraction))
        if self._on_progress:
            self._on_progress(overall, f"{self.stage_name}: {msg}" if msg else self.stage_name)

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            from storyforge.util.proc import Cancelled

            raise Cancelled("job cancelled")
