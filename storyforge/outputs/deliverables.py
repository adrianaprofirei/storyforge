"""Per-part deliverables: thumbnails at expressive moments, title/description/hashtags, the
editable .blend (relative paths, audio + textures packed)."""

from __future__ import annotations

import shutil
from pathlib import Path

from storyforge.util.ffmpeg import extract_frame
from storyforge.util.io import read_json, write_json

EXPRESSIVE = {"shocked": 1.0, "scared": 0.9, "excited": 0.95, "happy": 0.8, "angry": 0.85, "embarrassed": 0.75,
              "smug": 0.7, "confused": 0.6, "sad": 0.7, "determined": 0.65}
TIGHT = {"close_up": 1.0, "extreme_close_up": 0.9, "medium_close": 0.85, "over_the_shoulder": 0.6, "medium": 0.55,
         "two_shot": 0.5, "medium_wide": 0.45, "wide": 0.3, "establishing_wide": 0.2, "insert": 0.35}


def thumbnail_moments(timeline: dict, shotlist: dict, n: int = 3, offset: float = 0.0) -> list[dict]:
    """Score every shot by emotion x intensity x tightness and pick the n best (spread out)."""
    beats = {b["id"]: b for b in timeline["beats"]}
    scored = []
    for s in shotlist["shots"]:
        b = beats.get(s["beat"], {})
        score = (EXPRESSIVE.get(b.get("emotion"), 0.4) * (0.4 + float(b.get("intensity", 0.5)))
                 * TIGHT.get(s["type"], 0.5))
        if b.get("beat_type") in ("hook", "reveal", "cliffhanger", "payoff"):
            score *= 1.25
        t = s["start"] + (s["end"] - s["start"]) * 0.6
        scored.append({"t": t + offset, "shot": s["id"], "beat": s["beat"], "score": round(score, 3)})
    scored.sort(key=lambda x: -x["score"])
    picked: list[dict] = []
    for c in scored:
        if all(abs(c["t"] - p["t"]) > 4.0 for p in picked):
            picked.append(c)
        if len(picked) >= n:
            break
    return picked


def pick_thumbnails(ctx, video: Path, out_dir: Path, prefix: str = "final") -> list[Path]:
    tl = read_json(ctx.path("timeline.json"))
    sl = read_json(ctx.path("shotlist.json"))
    layout = read_json(ctx.path("captions", "layout.json"), {"offset": 0.0})
    moments = thumbnail_moments(tl, sl, 3, layout.get("offset", 0.0))
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    clean = video.with_name(video.stem + "_clean.mp4")
    src = clean if clean.is_file() else video
    for i, m in enumerate(moments, 1):
        p = out_dir / f"{prefix}_{i}.png"
        extract_frame(src, m["t"], p)
        paths.append(p)
    write_json(out_dir / f"{prefix}_moments.json", moments)
    return paths


def write_metadata(ctx, path: Path) -> dict:
    from storyforge.story.metadata import generate_metadata

    meta = generate_metadata(ctx.llm, read_json(ctx.path("screenplay.final.json")), ctx.bible())
    write_json(path, meta)
    return meta


def export_blend(ctx, dst: Path) -> Path:
    """Copy the episode .blend to the output folder with everything packed (portable project)."""
    src = ctx.path("scene", "episode.blend")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        return dst
    shutil.copy2(src, dst)
    try:
        from storyforge.render.blender import run_blender

        run_blender(ctx.settings, "pack", ["--blend", str(dst)], on_log=ctx.log, timeout=900)
    except Exception as exc:  # packing is a convenience; the copy with relative paths still works
        ctx.log(f"packing skipped: {str(exc)[:200]}")
    return dst
