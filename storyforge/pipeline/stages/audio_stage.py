"""audio_mix stage."""

from __future__ import annotations

from storyforge.audio.mixer import mix_episode
from storyforge.pipeline.runner import Stage
from storyforge.util.hashing import maybe_file_hash, stable_hash, tree_hash
from storyforge.util.io import read_json, write_json
from storyforge_blender.locations_data import get_location

MIX_VERSION = "1"


class AudioMixStage(Stage):
    code = ("audio/*.py",)
    name = "audio_mix"
    version = MIX_VERSION
    weight = 1.5

    def inputs(self, ctx):
        tl = read_json(ctx.path("timeline.json"))
        return {"timeline": maybe_file_hash(ctx.path("timeline.json")),
                "shots": maybe_file_hash(ctx.path("shotlist.json")),
                "voices": tree_hash(ctx.path("voices"), ["*.wav"]),
                "style": ctx.style(), "location": stable_hash(tl.get("location_info"))}

    def outputs(self, ctx):
        return [ctx.path("audio", "mix.wav"), ctx.path("audio", "mix_stats.json")]

    def run(self, ctx):
        tl = read_json(ctx.path("timeline.json"))
        blocking = read_json(ctx.path("blocking.json"), None)
        loc = tl.get("location_info") or {}
        room = loc.get("room") or get_location(loc.get("preset", tl["location"])).get("room", "medium_room")
        stats = mix_episode(tl, ctx.dir, ctx.sub("audio"), room, blocking)
        write_json(ctx.path("audio", "mix_stats.json"), stats)
        return stats
