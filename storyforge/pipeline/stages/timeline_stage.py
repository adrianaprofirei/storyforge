"""timeline + shot list stages."""

from __future__ import annotations

from storyforge.cinematography.designer import design_shots
from storyforge.pipeline.runner import Stage
from storyforge.staging import plan_blocking
from storyforge.timeline import build_timeline
from storyforge.util.hashing import maybe_file_hash, stable_hash, tree_hash
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


class PerformanceStage(Stage):
    """Body performance plan (NLA strips, props, extras) + facial performance (M3) per character."""

    name = "performance"
    version = "1"
    weight = 0.6

    def inputs(self, ctx):
        from storyforge.animation.library import manifest, mocap_files, retarget_code_hash

        return {"timeline": maybe_file_hash(ctx.path("timeline.json")),
                "blocking": maybe_file_hash(ctx.path("blocking.json")),
                "shots": maybe_file_hash(ctx.path("shotlist.json")),
                "cast": stable_hash({k: {kk: v.get(kk) for kk in ("look", "settings", "rig")} for k, v in ctx.cast().items()}),
                "mocap": [p.name + ":" + str(p.stat().st_size) for p in mocap_files()], "manifest": manifest(),
                "retarget": retarget_code_hash(),
                "code": tree_hash(_pkg_dir(), ["animation/*.py", "performance/*.py"])}

    def outputs(self, ctx):
        return [ctx.path("performance.json")]

    def run(self, ctx):
        from storyforge.animation.planner import plan_extras, plan_performance

        tl = read_json(ctx.path("timeline.json"))
        blocking = read_json(ctx.path("blocking.json"))
        perf = plan_performance(tl, blocking, ctx.cast(), tl["fps"], log=ctx.log,
                                use_mocap=ctx.settings.blender_mode is not None)
        loc = tl.get("location_info") or {}
        from storyforge_blender.locations_data import get_location

        preset = get_location(loc.get("preset", tl["location"]))
        perf["extras"] = plan_extras({**preset, **{k: v for k, v in loc.items() if k == "extras"}}, tl, tl["fps"])
        if perf["extras"]:
            from storyforge.animation.procedural import builtin_clips

            lib = builtin_clips(tl["fps"])
            for ex in perf["extras"]:
                for st in ex["strips"]:
                    if st["clip"] not in perf["clips"] and st["clip"] in lib:
                        c = lib[st["clip"]]
                        perf["clips"][st["clip"]] = {k: c[k] for k in ("name", "fps", "frames", "loop", "bones", "root",
                                                                       "root_normalized", "contacts", "category",
                                                                       "source")}
        from storyforge.performance.face import plan_faces

        faces, fx = plan_faces(tl, blocking, ctx.cast(), tl["fps"], read_json(ctx.path("shotlist.json"), None))
        for cid, f in faces.items():
            perf["characters"].setdefault(cid, {})["face"] = f
        perf["fx"] = fx
        write_json(ctx.path("performance.json"), perf, indent=None)
        return {"clips": len(perf["clips"]), "props": len(perf["props"]), "extras": len(perf["extras"]),
                "mocap": perf.get("mocap_used", [])}


def _pkg_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[2]
