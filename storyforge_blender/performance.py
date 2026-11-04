"""Character performance from the scene spec (body + face)."""

from __future__ import annotations

from storyforge_blender import animate


def apply_all(scene, spec: dict, characters: dict, mats, set_builder) -> None:
    fps = int(spec["fps"])
    fs, fe = int(spec["frame_start"]), int(spec["frame_end"])
    for cs in spec["characters"]:
        c = characters[cs["id"]]
        perf = cs.get("performance", {})
        speaking = [tuple(x) for x in perf.get("speaking_frames", [])]
        animate.simple_performance(c["rig"], fs, fe, speaking, fps)
        face = cs.get("face", {})
        animate.apply_shape_key_tracks(c["mouth"], face.get("mouth", {}), "LINEAR")
        animate.apply_shape_key_tracks(c["brows"], face.get("brows", {}), "BEZIER")
        animate.apply_prop_tracks(c["eyes"], face.get("eyes", {}), "BEZIER")
        animate.apply_color_alpha(c["blush"], face.get("blush", []), "BEZIER")
