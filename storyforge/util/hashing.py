"""Content hashing used by the stage cache.

`stable_hash` hashes any JSON-like structure canonically (sorted keys, no whitespace,
floats rounded to 6 decimals so that harmless float noise does not bust caches).
`file_hash` hashes file *content* and memoises on (path, size, mtime) so hashing the
same multi-megabyte WAV/PNG repeatedly is free.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_FILE_MEMO: dict[tuple[str, int, int], str] = {}


def _normalize(obj: Any) -> Any:
    if isinstance(obj, float):
        r = round(obj, 6)
        return 0.0 if r == 0 else r
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, set):
        return sorted(_normalize(v) for v in obj)
    if hasattr(obj, "model_dump"):
        return _normalize(obj.model_dump(mode="json"))
    return obj


def stable_json(obj: Any) -> str:
    return json.dumps(_normalize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_hash(*parts: Any, length: int = 20) -> str:
    h = hashlib.sha256(stable_json(list(parts)).encode("utf-8")).hexdigest()
    return h[:length]


def file_hash(path: str | os.PathLike, length: int = 20) -> str:
    p = Path(path)
    st = p.stat()
    key = (str(p.resolve()), st.st_size, st.st_mtime_ns)
    memo = _FILE_MEMO.get(key)
    if memo is None:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        memo = h.hexdigest()
        _FILE_MEMO[key] = memo
    return memo[:length]


def maybe_file_hash(path: str | os.PathLike | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    return file_hash(p) if p.is_file() else None


def tree_hash(root: str | os.PathLike, patterns: Iterable[str] = ("**/*",), length: int = 20) -> str:
    """Hash of every file under ``root`` matching ``patterns`` (relative path + content)."""
    root = Path(root)
    entries = []
    if root.exists():
        seen = set()
        for pat in patterns:
            for p in sorted(root.glob(pat)):
                if p.is_file() and "__pycache__" not in p.parts and p not in seen:
                    seen.add(p)
                    entries.append((p.relative_to(root).as_posix(), file_hash(p)))
    entries.sort()
    return stable_hash(entries, length=length)
