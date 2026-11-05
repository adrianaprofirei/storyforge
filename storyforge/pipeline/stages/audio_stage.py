"""audio_mix stage."""

from __future__ import annotations

from storyforge.audio.mixer import mix_episode
from storyforge.models.constants import RECAP_SPLITS
from storyforge.pipeline.runner import Stage
from storyforge.quality.autofix import section
from storyforge.util.hashing import maybe_file_hash, stable_hash, tree_hash
from storyforge.util.io import read_json, write_json
from storyforge_blender.locations_data import get_location

MIX_VERSION = "3"


class AudioMixStage(Stage):
    code = ("audio/*.py",)
    name = "audio_mix"
    version = MIX_VERSION
    weight = 1.5

    def inputs(self, ctx):
        from storyforge.audio.library import LIB_VERSION, _user_entries
        from storyforge.pipeline.stages.deliver import recap_info

        tl = read_json(ctx.path("timeline.json"))
        rc = recap_info(ctx)
        return {"timeline": maybe_file_hash(ctx.path("timeline.json")),
                "shots": maybe_file_hash(ctx.path("shotlist.json")),
                "performance": maybe_file_hash(ctx.path("performance.json")),
                "voices": tree_hash(ctx.path("voices"), ["*.wav"]),
                "style": ctx.style(), "location": stable_hash(tl.get("location_info")),
                "library": [LIB_VERSION, stable_hash([(e["file"], e["tags"]) for e in _user_entries("sfx")]),
                            stable_hash([(e["file"], e["moods"]) for e in _user_entries("music")])],
                "recap": [rc["seconds"], RECAP_SPLITS] if rc else 0.0, "fixes": stable_hash(section(ctx, "audio"))}

    def outputs(self, ctx):
        return [ctx.path("audio", "mix.wav"), ctx.path("audio", "mix_stats.json"), ctx.path("audio", "cues.json")]

    def run(self, ctx):
        from storyforge.audio.library import ensure_library
        from storyforge.audio.sfx import plan_ambience, plan_music, plan_sfx
        from storyforge.pipeline.stages.deliver import recap_info
        from storyforge.pipeline.stages.timeline_stage import _is_finale

        ensure_library(log=ctx.log)
        tl = read_json(ctx.path("timeline.json"))
        blocking = read_json(ctx.path("blocking.json"), None)
        shots = read_json(ctx.path("shotlist.json"), {"shots": []})
        perf = read_json(ctx.path("performance.json"), {})
        loc = tl.get("location_info") or {}
        room = loc.get("room") or get_location(loc.get("preset", tl["location"])).get("room", "medium_room")
        cues = plan_sfx(tl, shots, perf, blocking or {}, ctx.style())
        music = plan_music(tl, _is_finale(ctx), cues)
        amb = plan_ambience(tl, perf)
        rc = recap_info(ctx)
        lead = float(rc["seconds"]) if rc else 0.0
        lead_cues = []
        if lead > 0:
            # swell under the montage, a whoosh on every recap cut, a soft hit into the new part
            cuts = [round(lead * sum(RECAP_SPLITS[:k]), 3) for k in range(len(RECAP_SPLITS))]
            lead_cues = [{"t": 0.0, "tag": "recap", "gain_db": -10, "pan": 0.0}]
            lead_cues += [{"t": t, "tag": "whoosh", "gain_db": -12, "pan": 0.0} for t in cuts]
            lead_cues.append({"t": max(0.0, lead - 0.15), "tag": "impact_soft", "gain_db": -14, "pan": 0.0})
        fixes = section(ctx, "audio")
        kw = {"ceiling_db": float(fixes["ceiling_db"])} if fixes.get("ceiling_db") is not None else {}
        stats = mix_episode(tl, ctx.dir, ctx.sub("audio"), room, blocking, sfx_cues=cues, music_plan=music,
                            ambience=amb, lead_seconds=lead, lead_cues=lead_cues, **kw)
        write_json(ctx.path("audio", "cues.json"), {"sfx": cues, "music": music, "ambience": amb, "lead": lead_cues})
        write_json(ctx.path("audio", "mix_stats.json"), stats)
        return stats
