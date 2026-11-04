"""Post-build analysis pass feeding the quality gates.

For every shot, frames are sampled (every 2nd frame) and for each character we record world
positions of the head, hands, feet and hips, the projected head box in the shot camera (on/off
screen), arm elevation (T-pose detection), whether the rig has any animation, foot heights
(contact) and hand-to-torso distances (interpenetration). The camera transform per sample gives
camera motion; together with body motion this detects static shots.
"""

from __future__ import annotations

import math

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


def _bone_world(rig, name):
    pb = rig.pose.bones.get(name)
    if pb is None:
        return None
    return rig.matrix_world @ pb.head, rig.matrix_world @ pb.tail


def _arm_elevation(rig, side):
    ua = _bone_world(rig, f"upper_arm.{side}")
    if ua is None:
        return None
    d = (ua[1] - ua[0]).normalized()
    return math.degrees(math.asin(max(-1.0, min(1.0, d.z))))


def analyze(scene, spec: dict, built: dict, step: int = 2) -> dict:
    chars = built["characters"]
    out = {"fps": spec["fps"], "shots": [], "characters": {}}
    for cid, c in chars.items():
        rig = c["rig"]
        has_anim = bool(rig.animation_data and (rig.animation_data.action or rig.animation_data.nla_tracks))
        out["characters"][cid] = {"has_animation": has_anim, "head_size": c["metrics"]["head_size"],
                                  "torso_w": c["metrics"]["torso_w"], "torso_d": c["metrics"]["torso_d"]}
    cams = {o.get("sf_shot"): o for o in bpy.data.objects if o.type == "CAMERA" and o.get("sf_shot")}
    for s in spec["shots"]:
        cam = cams.get(s["id"])
        samples = []
        frames = list(range(s["frame_start"], s["frame_end"] + 1, step))
        if frames and frames[-1] != s["frame_end"]:
            frames.append(s["frame_end"])
        for f in frames:
            scene.frame_set(f)
            entry = {"frame": f, "camera": None, "chars": {}}
            if cam is not None:
                entry["camera"] = {"loc": list(cam.matrix_world.translation),
                                   "rot": list(cam.matrix_world.to_euler()), "lens": cam.data.lens}
            for cid, c in chars.items():
                rig = c["rig"]
                head = _bone_world(rig, "head")
                d = {}
                if head:
                    hc = (head[0] + head[1]) / 2
                    d["head"] = list(hc)
                    if cam is not None:
                        hs = c["metrics"]["head_size"] * 0.5
                        pts = [world_to_camera_view(scene, cam, hc + Vector(o)) for o in
                               ((hs, 0, hs), (-hs, 0, hs), (hs, 0, -hs), (-hs, 0, -hs), (0, 0, 0))]
                        xs, ys = [p.x for p in pts], [p.y for p in pts]
                        front = all(p.z > 0 for p in pts)
                        d["head_screen"] = [min(xs), min(ys), max(xs), max(ys)] if front else None
                for name in ("hand.L", "hand.R", "foot.L", "foot.R", "hips", "chest"):
                    bw = _bone_world(rig, name)
                    if bw:
                        d[name] = list(bw[1] if name.startswith("hand") else bw[0])
                d["arm_elev"] = [_arm_elevation(rig, "L"), _arm_elevation(rig, "R")]
                d["root"] = list(rig.matrix_world.translation)
                entry["chars"][cid] = d
            samples.append(entry)
        out["shots"].append({"id": s["id"], "frame_start": s["frame_start"], "frame_end": s["frame_end"],
                             "samples": samples})
    return out
