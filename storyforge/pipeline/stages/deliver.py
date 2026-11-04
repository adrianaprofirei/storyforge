"""captions + mux + quality + deliverables stages."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from storyforge.captions.ass import build_ass, build_graphics_ass, build_srt
from storyforge.pipeline.runner import Stage
from storyforge.util.hashing import maybe_file_hash, tree_hash
from storyforge.util.io import read_json, write_json

MUX_VERSION = "1"


def recap_info(ctx) -> dict | None:
    """Recap segment for parts 2+ (built in the mux stage from the previous part's video)."""
    meta = ctx.meta()
    if meta.get("part", 1) <= 1:
        return None
    prev = ctx.project.previous_episode(ctx.episode_id)
    if not prev:
        return None
    fmt = ctx.bible().get("format", {})
    seconds = float(fmt.get("recap_seconds", 2.5))
    prev_dir = ctx.project.episode_dir(prev)
    video = None
    for preset in (ctx.options.preset, "final", "draft", "proxy"):
        cand = prev_dir / "output" / f"{prev}_{preset}_clean.mp4"
        if cand.is_file():
            video = cand
            break
    return {"previous": prev, "seconds": seconds, "video": str(video) if video else None,
            "position": fmt.get("recap_position", "open")}


class CaptionsStage(Stage):
    code = ("captions/*.py",)
    name = "captions"
    version = "1"
    weight = 0.2

    def inputs(self, ctx):
        bible = ctx.bible()
        rc = recap_info(ctx)
        return {"timeline": maybe_file_hash(ctx.path("timeline.json")),
                "style": (bible.get("look", {}) or {}).get("caption_style", "bold_pop"),
                "accent": (bible.get("look", {}) or {}).get("accent_color"),
                "card": bible.get("format", {}).get("part_card"), "part": ctx.meta().get("part"),
                "recap": rc["seconds"] if rc else None}

    def outputs(self, ctx):
        return [ctx.path("captions", "captions.ass"), ctx.path("captions", "captions.srt"),
                ctx.path("captions", "graphics.ass"), ctx.path("captions", "layout.json")]

    def run(self, ctx):
        tl = read_json(ctx.path("timeline.json"))
        bible = ctx.bible()
        look = bible.get("look", {}) or {}
        rc = recap_info(ctx)
        offset = rc["seconds"] if rc else 0.0
        ass, layout = build_ass(tl, look.get("caption_style", "bold_pop"), offset, accent=look.get("accent_color"))
        out = ctx.sub("captions")
        (out / "captions.ass").write_text(ass, encoding="utf-8")
        (out / "captions.srt").write_text(build_srt(tl, offset), encoding="utf-8")
        part = ctx.meta().get("part")
        gfx = build_graphics_ass(part if part else None, bible.get("format", {}).get("part_card", {}),
                                 (0.0, offset) if rc else None, offset, look.get("accent_color", "#FFD447"))
        (out / "graphics.ass").write_text(gfx, encoding="utf-8")
        write_json(out / "layout.json", {"offset": offset, "lines": layout})
        return {"caption_lines": len(layout)}


def _link_or_copy(src: Path, dst: Path):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def assemble_sequence(ctx, preset: str, n_frames: int) -> Path:
    """Hard-link every shot's frames into one numbered sequence (missing frames hold the previous)."""
    man = read_json(ctx.path("render", preset, "manifest.json"))
    seq = ctx.path("render", preset, "_seq")
    if seq.exists():
        shutil.rmtree(seq)
    seq.mkdir(parents=True)
    fs = man["frame_start"]
    last = None
    idx = 0
    for s in man["shots"]:
        d = ctx.dir / s["dir"]
        for f in range(s["frame_start"], s["frame_end"] + 1):
            p = d / f"frame_{f:04d}.png"
            if p.is_file():
                last = p
            if last is None:
                continue
            if f - fs >= n_frames:
                break
            _link_or_copy(last, seq / f"{idx:06d}.png")
            idx += 1
    while idx < n_frames and last is not None:
        _link_or_copy(last, seq / f"{idx:06d}.png")
        idx += 1
    return seq


class MuxStage(Stage):
    code = ("render/finishing.py",)
    name = "mux"
    version = MUX_VERSION
    weight = 2.0

    def enabled(self, ctx):
        return not ctx.options.skip_render

    def _names(self, ctx):
        p = ctx.options.preset
        return ctx.path("output", f"{ctx.episode_id}_{p}.mp4"), ctx.path("output", f"{ctx.episode_id}_{p}_clean.mp4")

    def inputs(self, ctx):
        p = ctx.options.preset
        rc = recap_info(ctx)
        look = ctx.bible().get("look", {}) or {}
        return {"render": maybe_file_hash(ctx.path("render", p, "manifest.json")),
                "mix": maybe_file_hash(ctx.path("audio", "mix.wav")),
                "captions": tree_hash(ctx.path("captions"), ["*.ass"]), "grade": look.get("grade"),
                "recap": {**rc, "video_hash": maybe_file_hash(rc["video"]) if rc and rc.get("video") else None} if rc else None}

    def outputs(self, ctx):
        return list(self._names(ctx))

    def run(self, ctx):
        from storyforge.render.finishing import encode_episode

        preset = ctx.options.preset
        tl = read_json(ctx.path("timeline.json"))
        n_frames = tl["frames"]
        seq = assemble_sequence(ctx, preset, n_frames)
        look = ctx.bible().get("look", {}) or {}
        out_cap, out_clean = self._names(ctx)
        out_cap.parent.mkdir(parents=True, exist_ok=True)
        from storyforge.lighting.grades import resolve_grade

        info = encode_episode(seq_dir=seq, fps=tl["fps"], mix=ctx.path("audio", "mix.wav"),
                              captions_dir=ctx.path("captions"), out_captioned=out_cap, out_clean=out_clean,
                              grade=resolve_grade(look.get("grade")), preset=preset, recap=recap_info(ctx),
                              log=ctx.log)
        shutil.rmtree(seq, ignore_errors=True)
        return info


class QualityStage(Stage):
    code = ("quality/*.py",)
    name = "quality"
    version = "1"
    weight = 0.5

    def inputs(self, ctx):
        p = ctx.options.preset
        out_cap = ctx.path("output", f"{ctx.episode_id}_{p}.mp4")
        return {"video": maybe_file_hash(out_cap), "analysis": maybe_file_hash(ctx.path("scene", "analysis.json")),
                "timeline": maybe_file_hash(ctx.path("timeline.json")), "shots": maybe_file_hash(ctx.path("shotlist.json")),
                "mix": maybe_file_hash(ctx.path("audio", "mix.wav")),
                "layout": maybe_file_hash(ctx.path("captions", "layout.json")), "preset": p}

    def outputs(self, ctx):
        return [ctx.path("quality", f"report_{ctx.options.preset}.json")]

    def run(self, ctx):
        from storyforge.quality.gates import run_gates

        report = run_gates(ctx)
        write_json(ctx.path("quality", f"report_{ctx.options.preset}.json"), report)
        md = [f"# Quality report: {ctx.episode_id} ({ctx.options.preset})", "",
              f"**Result:** {'PASS' if report['passed'] else 'FAIL'}", ""]
        for g in report["gates"]:
            md.append(f"- **{g['name']}**: {g['status'].upper()} - {g['summary']}")
        (ctx.path("quality") / f"report_{ctx.options.preset}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        return {"passed": report["passed"], "failed": [g["name"] for g in report["gates"] if g["status"] == "fail"]}


class DeliverablesStage(Stage):
    code = ("outputs/*.py", "story/metadata.py")
    name = "deliverables"
    version = "1"
    weight = 0.6

    def enabled(self, ctx):
        return not ctx.options.skip_render

    def inputs(self, ctx):
        p = ctx.options.preset
        return {"video": maybe_file_hash(ctx.path("output", f"{ctx.episode_id}_{p}.mp4")),
                "blend": maybe_file_hash(ctx.path("scene", "episode.blend")),
                "screenplay": maybe_file_hash(ctx.path("screenplay.final.json")), "llm": ctx.llm.name}

    def outputs(self, ctx):
        p = ctx.options.preset
        return [ctx.path("output", f"{ctx.episode_id}_metadata.json"), ctx.path("output", f"{ctx.episode_id}.blend"),
                ctx.path("output", "thumbnails", f"{p}_1.png")]

    def run(self, ctx):
        from storyforge.outputs.deliverables import export_blend, pick_thumbnails, write_metadata

        p = ctx.options.preset
        out = ctx.sub("output")
        video = ctx.path("output", f"{ctx.episode_id}_{p}.mp4")
        thumbs = pick_thumbnails(ctx, video, out / "thumbnails", prefix=p)
        meta = write_metadata(ctx, out / f"{ctx.episode_id}_metadata.json")
        blend = export_blend(ctx, out / f"{ctx.episode_id}.blend")
        return {"thumbnails": [str(t) for t in thumbs], "titles": meta.get("titles", [])[:1], "blend": str(blend)}
