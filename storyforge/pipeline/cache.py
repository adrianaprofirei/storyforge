"""Content-hash caching.

Two levels:

* **Stage records** (``<episode>/.cache/<stage>.json``): a stage is skipped when the hash of
  its declared inputs (upstream file contents + parameters + stage code version) equals the
  recorded key and all its declared outputs still exist. Because keys are computed from
  *content*, an upstream stage that re-runs but produces identical bytes does not invalidate
  anything downstream.
* **Item caches** (``$DATA/cache/<kind>/<hash>.*``): fine-grained, shared across episodes —
  one entry per TTS line, lip-sync analysis, retargeted mocap clip, rendered shot... so editing
  one beat only re-synthesises that line and re-renders the shots it touches.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from storyforge import PIPELINE_FORMAT_VERSION
from storyforge.util.hashing import stable_hash
from storyforge.util.io import ensure_dir, read_json, write_json


def stage_key(name: str, version: str | int, inputs: Any) -> str:
    return stable_hash("stage", name, str(version), PIPELINE_FORMAT_VERSION, inputs)


class StageRecords:
    def __init__(self, episode_dir: Path):
        self.dir = ensure_dir(Path(episode_dir) / ".cache")

    def path(self, stage: str) -> Path:
        return self.dir / f"{stage}.json"

    def get(self, stage: str) -> dict | None:
        return read_json(self.path(stage), None)

    def is_fresh(self, stage: str, key: str, outputs: list[Path]) -> bool:
        rec = self.get(stage)
        if not rec or rec.get("key") != key:
            return False
        return all(Path(p).exists() for p in outputs)

    def put(self, stage: str, key: str, outputs: list[Path], seconds: float, extra: dict | None = None):
        write_json(self.path(stage), {
            "stage": stage, "key": key, "finished_at": time.time(), "seconds": round(seconds, 3),
            "outputs": [str(p) for p in outputs], **(extra or {}),
        })

    def invalidate(self, stage: str) -> None:
        p = self.path(stage)
        if p.exists():
            p.unlink()


class ItemCache:
    """Directory-based content-addressed cache for individual artifacts."""

    def __init__(self, root: Path):
        self.root = ensure_dir(root)

    def path(self, key: str, suffix: str) -> Path:
        sub = ensure_dir(self.root / key[:2])
        return sub / f"{key}{suffix}"

    def get(self, key: str, suffix: str) -> Path | None:
        p = self.path(key, suffix)
        return p if p.exists() else None

    def meta(self, key: str) -> dict | None:
        return read_json(self.path(key, ".json"), None)

    def put_meta(self, key: str, meta: dict) -> Path:
        return write_json(self.path(key, ".json"), meta)
