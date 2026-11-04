"""Character performance from the scene spec: body (NLA layers + post passes), props, extras, face."""

from __future__ import annotations

import time

from storyforge_blender import animate, nla
from storyforge_blender.animate import relaxed_pose


def log(msg: str) -> None:
    print(f"SF_LOG {msg}", flush=True)


def _relaxed_ref(rig) -> dict:
    return {k: list(v) for k, v in relaxed_pose().items()}


def apply_body(scene, spec: dict, characters: dict) -> dict:
    fps = int(spec["fps"])
    fs, fe = int(spec["frame_start"]), int(spec["frame_end"])
    clips = spec.get("clips", {})
    stats = {}
    for cs in spec["characters"]:
        c = characters[cs["id"]]
        rig = c["rig"]
        perf = cs.get("performance", {})
        if perf.get("strips") and clips:
            nla.apply_strips(rig, perf, clips, _relaxed_ref(rig), cs["id"])
        else:  # no plan (old specs): relaxed pose + breathing
            speaking = [tuple(x) for x in perf.get("speaking_frames", [])]
            animate.simple_performance(rig, fs, fe, speaking, fps)
        nla.apply_squash(rig, perf.get("squash", []))
    # post passes need the evaluated animation of the whole scene
    for cs in spec["characters"]:
        c = characters[cs["id"]]
        perf = cs.get("performance", {})
        t = time.time()
        st = {}
        if perf.get("foot_lock", True):
            st["foot_lock"] = nla.foot_lock(scene, c["rig"], c["metrics"], fs, fe, fps)
        if perf.get("collision_fix", True):
            st["collision_frames"] = nla.collision_fix(scene, c["rig"], c["metrics"], fs, fe)
        if perf.get("secondary", True):
            bones = [b for b in ("hair_1", "backpack") if (b == "hair_1" and c.get("has_ponytail")) or
                     (b == "backpack" and c.get("has_backpack"))]
            st["secondary"] = nla.secondary_motion(scene, c["rig"], fs, fe, fps, bones=tuple(bones)) if bones else 0
        stats[cs["id"]] = st
        log(f"{cs['id']} body passes {time.time() - t:.1f}s {st}")
    return stats


def apply_face(spec: dict, characters: dict) -> None:
    for cs in spec["characters"]:
        c = characters[cs["id"]]
        face = cs.get("face", {})
        animate.apply_shape_key_tracks(c["mouth"], face.get("mouth", {}), "LINEAR")
        animate.apply_shape_key_tracks(c["brows"], face.get("brows", {}), "BEZIER")
        animate.apply_prop_tracks(c["eyes"], face.get("eyes", {}), "BEZIER")
        animate.apply_color_alpha(c["blush"], face.get("blush", []), "BEZIER")


def apply_extras(scene, spec: dict, mats) -> list:
    from storyforge_blender.character import build_character

    extras = []
    clips = spec.get("clips", {})
    fps = int(spec["fps"])
    fs = int(spec["frame_start"])
    for ex in spec.get("extras", []):
        c = build_character({"id": ex["id"], "look": ex["look"]}, mats, scene)
        animate.apply_root_path(c["rig"], ex["path"], fs, fps)
        plan = {"strips": ex["strips"], "hip_height": ex.get("hip_height", 0.43)}
        nla.apply_strips(c["rig"], plan, clips, _relaxed_ref(c["rig"]), ex["id"])
        extras.append(c)
    return extras


def apply_all(scene, spec: dict, characters: dict, mats, set_builder) -> None:
    from storyforge_blender.props import build_props

    t = time.time()
    if spec.get("props"):
        build_props(scene, spec["props"], characters, mats, int(spec["fps"]), int(spec["frame_start"]),
                    int(spec["frame_end"]))
    apply_face(spec, characters)
    if spec.get("extras"):
        apply_extras(scene, spec, mats)
    apply_body(scene, spec, characters)
    try:
        from storyforge_blender import fx

        fx.build_fx(scene, spec, characters, mats)
    except ImportError:
        pass
    log(f"performance applied in {time.time() - t:.1f}s")
