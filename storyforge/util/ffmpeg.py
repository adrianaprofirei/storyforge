"""ffmpeg / ffprobe helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from storyforge.config import get_settings
from storyforge.util.proc import run


class FFmpegMissing(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    exe = get_settings().tool("ffmpeg")
    if not exe:
        raise FFmpegMissing("ffmpeg not found: install it and/or set FFMPEG_PATH in .env")
    return exe


def ffprobe_exe() -> str:
    exe = get_settings().tool("ffprobe")
    if not exe:
        raise FFmpegMissing("ffprobe not found: install it and/or set FFPROBE_PATH in .env")
    return exe


def ffmpeg(args: list[str | os.PathLike], cwd: str | os.PathLike | None = None, **kw):
    return run([ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", *map(str, args)], cwd=cwd, **kw)


def probe(path: str | os.PathLike) -> dict:
    res = run([ffprobe_exe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(res.output)


def duration(path: str | os.PathLike) -> float:
    info = probe(path)
    try:
        return float(info["format"]["duration"])
    except (KeyError, ValueError):
        for s in info.get("streams", []):
            if "duration" in s:
                return float(s["duration"])
    return 0.0


def has_filter(name: str) -> bool:
    res = run([ffmpeg_exe(), "-hide_banner", "-filters"], check=False)
    return re.search(rf"\s{re.escape(name)}\s", res.output) is not None


def capabilities() -> dict:
    out = {"ffmpeg": None, "libass": False, "libx264": False, "ebur128": False}
    try:
        exe = ffmpeg_exe()
    except FFmpegMissing:
        return out
    out["ffmpeg"] = exe
    filt = run([exe, "-hide_banner", "-filters"], check=False).output
    enc = run([exe, "-hide_banner", "-encoders"], check=False).output
    out["libass"] = bool(re.search(r"\sass\s", filt)) and bool(re.search(r"\ssubtitles\s", filt))
    out["ebur128"] = " ebur128 " in filt
    out["libx264"] = "libx264" in enc
    return out


def ebur128_stats(path: str | os.PathLike) -> dict:
    """Integrated loudness (LUFS), loudness range and true peak (dBTP) measured by ffmpeg."""
    res = ffmpeg(["-i", str(path), "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"], check=False)
    text = res.output
    stats = {}
    m = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", text)
    if m:
        stats["integrated_lufs"] = float(m[-1]) if m[-1] != "-inf" else float("-inf")
    m = re.findall(r"LRA:\s+(-?[\d.]+) LU", text)
    if m:
        stats["lra"] = float(m[-1])
    m = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", text)
    if m:
        stats["true_peak_dbtp"] = float(m[-1]) if m[-1] != "-inf" else float("-inf")
    return stats


def extract_frame(video: str | os.PathLike, t: float, out_png: str | os.PathLike, width: int | None = None):
    vf = [f"scale={width}:-2"] if width else []
    args = ["-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1"]
    if vf:
        args += ["-vf", ",".join(vf)]
    args += [str(out_png)]
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(args)
    return Path(out_png)
