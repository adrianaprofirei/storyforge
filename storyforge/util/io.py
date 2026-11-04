"""Small, atomic file helpers (JSON/YAML) shared by every stage."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def _read_umask() -> int:
    # read once at import (os.umask is process-wide; toggling it later would race with worker threads)
    mask = os.umask(0o022)
    os.umask(mask)
    return mask


_UMASK = _read_umask()


def ensure_dir(path: str | os.PathLike) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def atomic_write_bytes(path: str | os.PathLike, data: bytes) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o666 & ~_UMASK)  # mkstemp creates 0600 files; use normal permissions
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def atomic_write_text(path: str | os.PathLike, text: str) -> Path:
    return atomic_write_bytes(path, text.encode("utf-8"))


def _json_default(o: Any):
    if isinstance(o, Path):
        return o.as_posix()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if hasattr(o, "tolist"):
        return o.tolist()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def write_json(path: str | os.PathLike, obj: Any, indent: int | None = 2) -> Path:
    return atomic_write_text(path, json.dumps(obj, indent=indent, ensure_ascii=False, default=_json_default) + "\n")


def read_json(path: str | os.PathLike, default: Any = ...) -> Any:
    p = Path(path)
    if not p.is_file():
        if default is ...:
            raise FileNotFoundError(p)
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_yaml(path: str | os.PathLike, obj: Any) -> Path:
    text = yaml.safe_dump(json.loads(json.dumps(obj, default=_json_default)), sort_keys=False,
                          allow_unicode=True, width=100)
    return atomic_write_text(path, text)


def read_yaml(path: str | os.PathLike, default: Any = ...) -> Any:
    p = Path(path)
    if not p.is_file():
        if default is ...:
            raise FileNotFoundError(p)
        return default
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_data(path: str | os.PathLike) -> Any:
    """Read JSON or YAML based on extension."""
    p = Path(path)
    if p.suffix.lower() in {".yaml", ".yml"}:
        return read_yaml(p)
    return read_json(p)


def rel_or_abs(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
