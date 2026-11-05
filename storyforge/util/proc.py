"""Subprocess helpers: list-args only (no shell), UTF-8 safe, streaming logs, cancellable.

Windows note: we never use ``shell=True`` and always pass argument lists, so paths with
spaces (``C:\\Program Files\\Blender Foundation\\...``) work without quoting.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from storyforge.config import IS_WINDOWS


class ProcessError(RuntimeError):
    def __init__(self, cmd: Sequence[str], returncode: int, output: str):
        tail = "\n".join(output.strip().splitlines()[-40:])
        super().__init__(f"command failed ({returncode}): {' '.join(map(str, cmd[:6]))} ...\n{tail}")
        self.cmd = list(cmd)
        self.returncode = returncode
        self.output = output


class Cancelled(RuntimeError):
    pass


@dataclass
class ProcResult:
    returncode: int
    output: str
    seconds: float


def run(cmd: Sequence[str | os.PathLike], *, cwd: str | os.PathLike | None = None,
        env: dict | None = None, timeout: float | None = None,
        on_line: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None, check: bool = True,
        input_text: str | None = None) -> ProcResult:
    """Run a command, streaming merged stdout/stderr lines to ``on_line``."""
    args = [str(c) for c in cmd]
    full_env = os.environ.copy()
    if env:
        full_env.update({k: str(v) for k, v in env.items()})
    full_env.setdefault("PYTHONIOENCODING", "utf-8")
    creationflags = 0
    if IS_WINDOWS:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    start = time.time()
    proc = subprocess.Popen(
        args, cwd=str(cwd) if cwd else None, env=full_env,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    lines: list[str] = []

    def reader():
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            lines.append(line)
            if on_line:
                try:
                    on_line(line)
                except Exception:  # never let a log callback kill the process reader
                    pass
        proc.stdout.close()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    if input_text is not None and proc.stdin:
        try:
            proc.stdin.write(input_text.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
    try:
        while True:
            try:
                proc.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled("cancelled")
            if timeout is not None and time.time() - start > timeout:
                proc.kill()
                proc.wait()
                raise ProcessError(args, -9, "\n".join(lines) + f"\n[timeout after {timeout}s]")
    finally:
        t.join(timeout=5)
    out = "\n".join(lines)
    res = ProcResult(proc.returncode, out, time.time() - start)
    if check and proc.returncode != 0:
        raise ProcessError(args, proc.returncode, out)
    return res


def run_quiet(cmd: Sequence[str | os.PathLike], **kw) -> ProcResult:
    return run(cmd, **kw)


def which_or_none(path: str | None) -> str | None:
    return path if path and Path(path).exists() else None
