"""Running StoryForge scripts in Blender as a subprocess.

* Real Blender (BLENDER_PATH): ``blender -b --factory-startup --python-exit-code 1 -P entry.py -- cmd ...``
* bpy module (BLENDER_PYTHON, dev/CI): ``python entry.py -- cmd ...``
Both stream stdout; lines prefixed ``SF_FRAME_DONE``/``SF_LOG``/``SF_ERROR`` drive progress and logs.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path

from storyforge.config import BLENDER_PKG_DIR, Settings
from storyforge.util.proc import ProcessError, run

ENTRY = BLENDER_PKG_DIR / "entry.py"
NOISE = re.compile(r"^(EGL Error|Fra:\d+ Mem|Read blend:|Blender quit|Warning: Your graphics)")


class BlenderUnavailable(RuntimeError):
    pass


def invocation(settings: Settings, command: str, args: list[str]) -> list[str]:
    prefix = settings.blender_command()
    if prefix is None:
        raise BlenderUnavailable(
            "Blender not found. Set BLENDER_PATH in .env to your blender executable "
            "(e.g. C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe), or BLENDER_PYTHON to a "
            "Python interpreter with the `bpy` module.")
    if settings.blender_mode == "blender":
        return [*prefix, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(ENTRY), "--", command, *args]
    return [*prefix, str(ENTRY), "--", command, *args]


def run_blender(settings: Settings, command: str, args: list[str], *, on_log: Callable[[str], None] | None = None,
                on_frame: Callable[[int], None] | None = None, cancel_event: threading.Event | None = None,
                timeout: float | None = None, log_file: Path | None = None) -> str:
    cmd = invocation(settings, command, args)
    lines: list[str] = []
    fh = open(log_file, "a", encoding="utf-8") if log_file else None

    def handle(line: str):
        if fh:
            fh.write(line + "\n")
        if line.startswith("SF_FRAME_DONE"):
            if on_frame:
                try:
                    on_frame(int(line.split()[1]))
                except (IndexError, ValueError):
                    pass
            return
        if NOISE.match(line):
            return
        lines.append(line)
        if on_log and (line.startswith("SF_LOG") or "Error" in line or "Traceback" in line):
            on_log(line.replace("SF_LOG ", ""))

    env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    try:
        res = run(cmd, on_line=handle, cancel_event=cancel_event, timeout=timeout or settings.blender_timeout,
                  env=env, cwd=str(BLENDER_PKG_DIR.parent))
    except ProcessError as exc:
        raise ProcessError(exc.cmd, exc.returncode, "\n".join(lines[-80:])) from None
    finally:
        if fh:
            fh.close()
    if any(line.startswith("SF_ERROR") for line in lines):
        raise ProcessError(cmd, 1, "\n".join(lines[-80:]))
    return res.output


def doctor(settings: Settings) -> dict | None:
    try:
        out = run_blender(settings, "doctor", [], timeout=300)
    except (BlenderUnavailable, ProcessError) as exc:
        return {"error": str(exc)[:500]}
    for line in out.splitlines():
        if line.startswith("SF_DOCTOR "):
            return json.loads(line[len("SF_DOCTOR "):])
    return None


def blender_available(settings: Settings) -> bool:
    return settings.blender_command() is not None


def cpu_count() -> int:
    return max(1, os.cpu_count() or 1)
