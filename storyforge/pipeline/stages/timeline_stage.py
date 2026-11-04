"""timeline + shot list stages."""

from __future__ import annotations

from storyforge.cinematography.designer import design_shots
from storyforge.pipeline.runner import Stage
from storyforge.staging import plan_blocking
from storyforge.timeline import build_timeline
from storyforge.util.hashing import maybe_file_hash, stable_hash
from storyforge.util.io import read_json, write_json


def _is_finale(ctx) -> bool:
    meta = ctx.meta()
    arc = ctx.project.arc(meta.get("arc_id", "")) or {}
    return meta.get("part", 1) >= (len(arc.get("parts", [])) or 1)


class TimelineStage(Stage):
    name = "timeline"
    version = "2"
    weight = 0.3

    def inputs(self, ctx):
        bible = ctx.bible()
        return {"screenplay": maybe_file_hash(ctx.path("screenplay.final.json")),
                "voices": maybe_file_hash(ctx.path("voices", "manifest.json")),
                "lipsync": maybe_file_hash(ctx.path("lipsync", "manifest.json")),
                "fps": ctx.fps, "finale": _is_finale(ctx), "limit": ctx.options.duration_limit,
                "characters": stable_hash([c.get("name") for c in bible.get("characters", [])]),
                "cast": stable_hash({k: v.get("look", {}).get("body") for k, v in ctx.cast().items()}),
                "location": stable_hash(ctx.project.location(read_json(ctx.path("screenplay.final.json"))["location"]))}

    def outputs(self, ctx):
        return [ctx.path("timeline.json"), ctx.path("blocking.json")]

    def run(self, ctx):
        sp = read_json(ctx.path("screenplay.final.json"))
        voices = read_json(ctx.path("voices", "manifest.json"))
        lips = read_json(ctx.path("lipsync", "manifest.json"))
        bible = ctx.bible()
        tl = build_timeline(sp, voices, lips, ctx.fps, bible, _is_finale(ctx), ctx.options.duration_limit)
        loc = ctx.project.location(sp["location"])
        tl["location_info"] = loc
        blocking = plan_blocking(tl, ctx.cast(), loc)
        write_json(ctx.path("timeline.json"), tl)
        write_json(ctx.path("blocking.json"), blocking)
        fmt = bible.get("format", {})
        lo, hi = fmt.get("part_min_seconds", 45), fmt.get("part_max_seconds", 90)
        if not ctx.options.duration_limit and not (lo <= tl["duration"] <= hi):
            ctx.log(f"WARNING: runtime {tl['duration']:.1f}s outside {lo}-{hi}s")
        return {"duration": tl["duration"], "frames": tl["frames"], "beats": len(tl["beats"])}


class ShotsStage(Stage):
    name = "shots"
    version = "2"
    weight = 0.3

    def inputs(self, ctx):
        return {"timeline": maybe_file_hash(ctx.path("timeline.json")),
                "blocking": maybe_file_hash(ctx.path("blocking.json")),
                "overrides": maybe_file_hash(ctx.path("shot_overrides.json"))}

    def outputs(self, ctx):
        return [ctx.path("shotlist.json")]

    def run(self, ctx):
        tl = read_json(ctx.path("timeline.json"))
        blocking = read_json(ctx.path("blocking.json"))
        overrides = read_json(ctx.path("shot_overrides.json"), {})
        sl = design_shots(tl, blocking, overrides)
        write_json(ctx.path("shotlist.json"), sl)
        return {"shots": len(sl["shots"])}
