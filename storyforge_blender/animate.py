"""Applying animation from the scene spec: root paths, base pose, face channels.

(M2/M3 layer the clip library, NLA blending, foot locking, secondary motion and full facial
performance on top of these primitives.)"""

from __future__ import annotations

import math

import bpy

from storyforge_blender import compat
from storyforge_blender.posing import mirror_q, q, to_local

RELAXED = {  # T-pose -> relaxed standing (armature-axis local deltas)
    "upper_arm.L": q("Y", 72) @ q("X", 0),
    "forearm.L": q("Z", -14),
    "hand.L": q("X", 0),
    "shoulder.L": q("Y", 4),
}


def relaxed_pose() -> dict:
    pose = dict(RELAXED)
    for k, v in list(RELAXED.items()):
        pose[k.replace(".L", ".R")] = mirror_q(v)
    return pose


def apply_root_path(rig, path: list, frame_start: int, fps: int):
    """path: [[t, x, y, yaw_deg], ...] -> keyed object location / rotation."""
    if not path:
        return
    lk, rk = [], []
    prev_yaw = None
    for t, x, y, yaw in path:
        f = frame_start + t * fps
        if prev_yaw is not None:
            while yaw - prev_yaw > 180:
                yaw -= 360
            while yaw - prev_yaw < -180:
                yaw += 360
        prev_yaw = yaw
        lk.append((f, (x, y, 0.0)))
        rk.append((f, math.radians(yaw)))
    rig.location = lk[0][1]
    rig.rotation_euler = (0, 0, rk[0][1])
    if len(path) > 1:
        compat.set_vector_keys(rig, "location", lk, "BEZIER")
        compat.set_keys(rig, "rotation_euler", 2, rk, "BEZIER")


def key_pose(rig, pose: dict, frame: float, action_keys: dict):
    """Accumulate keyed quaternions {data_path: {idx: [(f, v)]}} for a pose dict (armature deltas)."""
    for bname, l_arm in pose.items():
        pb = rig.pose.bones.get(bname)
        if pb is None:
            continue
        loc = to_local(pb, l_arm)
        dp = f'pose.bones["{bname}"].rotation_quaternion'
        for i in range(4):
            action_keys.setdefault((dp, bname), {}).setdefault(i, []).append((frame, loc[i]))


def write_keys(rig, action_keys: dict, interpolation: str = "BEZIER"):
    for (dp, bname), per_idx in action_keys.items():
        for i, keys in per_idx.items():
            compat.set_keys(rig, dp, i, keys, interpolation, group=bname)


def apply_shape_key_tracks(obj, tracks: dict, interpolation: str = "LINEAR"):
    """tracks: {shape_key_name: [[frame, value], ...]} on a mesh with shape keys."""
    if not tracks or obj is None or obj.data.shape_keys is None:
        return
    key = obj.data.shape_keys
    kb = key.key_blocks
    for name, keys in tracks.items():
        if name not in kb or not keys:
            continue
        compat.set_keys(key, f'key_blocks["{name}"].value', 0, [(k[0], k[1]) for k in keys], interpolation)


def apply_prop_tracks(obj, tracks: dict, interpolation: str = "BEZIER"):
    """tracks: {custom_prop: [[frame, value], ...]} (eye props, etc.)."""
    if obj is None:
        return
    for name, keys in (tracks or {}).items():
        if not keys:
            continue
        if name not in obj.keys():
            obj[name] = float(keys[0][1])
        compat.set_keys(obj, f'["{name}"]', 0, [(k[0], k[1]) for k in keys], interpolation)


def apply_color_alpha(obj, keys: list, interpolation: str = "BEZIER"):
    if obj is None or not keys:
        return
    compat.set_keys(obj, "color", 3, [(k[0], k[1]) for k in keys], interpolation)


def simple_performance(rig, frame_start: int, frame_end: int, speaking: list, fps: int):
    """M1 baseline: relaxed pose + breathing + small head nods while speaking."""
    keys: dict = {}
    pose = relaxed_pose()
    key_pose(rig, pose, frame_start, keys)
    key_pose(rig, pose, frame_end, keys)
    if speaking:
        nods = [(frame_start, 0.0)]
        for s, e in speaking:
            nods += [(s - 2, 0.0), (s + 4, 5.0), ((s + e) / 2, -2.5), (e + 3, 0.0)]
        nods.append((frame_end, 0.0))
        for f, ang in sorted(nods):
            key_pose(rig, {"head": q("X", -ang)}, f, keys)
    write_keys(rig, keys)
    # breathing on the chest via a cyclic modifier on a separate fcurve set
    chest = rig.pose.bones.get("chest")
    if chest is not None:
        period = int(fps * 3.4)
        kk = []
        for f in range(frame_start, frame_end + period, period // 2):
            phase = ((f - frame_start) // (period // 2)) % 2
            kk.append((f, 0.0 if phase == 0 else 0.012))
        compat.set_keys(rig, 'pose.bones["chest"].location', 1, kk, "BEZIER", group="chest")


def quiet_bpy_logs():
    try:
        bpy.app.debug_value = 0
    except Exception:
        pass
