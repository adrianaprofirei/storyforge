"""Mocap import (BVH / FBX / glTF) + retargeting onto the canonical clip format.

Algorithm (rest-pose relative, world space):
1. import the file into an empty scene, take the armature with the most bones;
2. map bones to canonical names (bonemap.auto_map, user overrides win);
3. facing correction G (yaw) so the source's left side is +X and it faces -Y like our rigs;
4. per frame and mapped bone: world delta D_src = R_pose @ R_rest^-1, corrected G D G^-1;
5. rest alignment: A = shortest rotation from the source rest direction to the canonical rest
   direction (handles A-pose vs T-pose); canonical world delta D = D_src @ A^-1;
6. unmapped canonical bones inherit their parent's D; local deltas L = D_parent^-1 @ D;
7. root motion = hips world offset / source hip height (applied scaled to the target), foot
   contacts from foot height, stride from root travel per cycle.
"""

from __future__ import annotations

import math
from pathlib import Path

import addon_utils
import bpy
from mathutils import Quaternion, Vector

from storyforge_blender.bonemap import CANONICAL, CANONICAL_PARENT, REST_DIR, auto_map, missing_required


def _enable(mod: str):
    try:
        addon_utils.enable(mod, default_set=True)
    except Exception:
        pass


def _import(path: str):
    ext = Path(path).suffix.lower()
    before = set(bpy.data.objects)
    if ext == ".bvh":
        _enable("io_anim_bvh")
        bpy.ops.import_anim.bvh(filepath=path, rotate_mode="NATIVE", axis_forward="-Z", axis_up="Y",
                                use_fps_scale=False, update_scene_fps=False, update_scene_duration=True)
    elif ext == ".fbx":
        _enable("io_scene_fbx")
        bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=False, ignore_leaf_bones=True)
    elif ext in (".glb", ".gltf"):
        _enable("io_scene_gltf2")
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise ValueError(f"unsupported animation file: {path}")
    new = [o for o in bpy.data.objects if o not in before]
    arms = [o for o in new if o.type == "ARMATURE"]
    if not arms:
        raise RuntimeError(f"no armature in {path}")
    return max(arms, key=lambda a: len(a.data.bones))


def _frame_range(arm) -> tuple[int, int]:
    ad = arm.animation_data
    if ad and ad.action:
        a, b = ad.action.frame_range
        return int(math.floor(a)), int(math.ceil(b))
    return bpy.context.scene.frame_start, bpy.context.scene.frame_end


def import_clip(path: str, user_map: dict | None = None, name: str | None = None) -> dict:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    arm = _import(path)
    names = [b.name for b in arm.data.bones]
    mapping = auto_map(names)
    if user_map:
        mapping.update({k: v for k, v in user_map.items() if v in names})
    missing = missing_required(mapping)
    if missing:
        raise RuntimeError(f"could not map required bones {missing}; provide a bone map (have: {names[:30]})")
    mw = arm.matrix_world
    rest_q = {c: (mw @ arm.data.bones[s].matrix_local).to_quaternion() for c, s in mapping.items()}
    rest_head = {c: mw @ arm.data.bones[s].head_local for c, s in mapping.items()}
    rest_tail = {c: mw @ arm.data.bones[s].tail_local for c, s in mapping.items()}
    # facing correction: source left (L - R hip/shoulder) -> +X
    left = Vector((0, 0, 0))
    for a, b in (("thigh.L", "thigh.R"), ("upper_arm.L", "upper_arm.R")):
        if a in rest_head and b in rest_head:
            left += rest_head[a] - rest_head[b]
    yaw = math.atan2(left.y, left.x)
    G = Quaternion((0, 0, 1), -yaw)
    Gi = G.inverted()
    hip_rest = G @ rest_head["hips"]
    floor_z = min((G @ rest_head[c]).z for c in rest_head)
    hip_h = max(1e-3, hip_rest.z - floor_z)
    # rest alignment rotations
    align = {}
    for c in mapping:
        d_src = (G @ (rest_tail[c] - rest_head[c]))
        if d_src.length < 1e-6:
            align[c] = Quaternion()
            continue
        d_src.normalize()
        align[c] = d_src.rotation_difference(Vector(REST_DIR[c]).normalized())
    f0, f1 = _frame_range(arm)
    fps = scene.render.fps / scene.render.fps_base
    bones_out = {c: [] for c in CANONICAL}
    root, foot_z = [], {"foot.L": [], "foot.R": []}
    for f in range(f0, f1 + 1):
        scene.frame_set(f)
        D = {}
        for c in CANONICAL:
            if c in mapping:
                pb = arm.pose.bones[mapping[c]]
                q_pose = (arm.matrix_world @ pb.matrix).to_quaternion()
                d_src = G @ (q_pose @ rest_q[c].inverted()) @ Gi
                D[c] = d_src @ align[c].inverted()
            else:
                parent = CANONICAL_PARENT[c]
                D[c] = D[parent] if parent else Quaternion()
        for c in CANONICAL:
            parent = CANONICAL_PARENT[c]
            L = D[c] if parent is None else D[parent].inverted() @ D[c]
            L.normalize()
            if bones_out[c] and sum(a * b for a, b in zip(bones_out[c][-1], L, strict=False)) < 0:
                L = -L  # keep quaternion hemisphere continuous for clean interpolation
            bones_out[c].append([round(v, 5) for v in L])
        hp = G @ (arm.matrix_world @ arm.pose.bones[mapping["hips"]].head)
        root.append([round((hp.x - hip_rest.x) / hip_h, 5), round((hp.y - hip_rest.y) / hip_h, 5),
                     round((hp.z - hip_rest.z) / hip_h, 5)])
        for side in ("L", "R"):
            key = f"foot.{side}"
            if key in mapping:
                fz = (G @ (arm.matrix_world @ arm.pose.bones[mapping[key]].head)).z
                foot_z[key].append((fz - floor_z) / hip_h)
    n = len(root)
    contacts = {}
    for key, zs in foot_z.items():
        if not zs:
            continue
        lo = min(zs)
        on = [z < lo + 0.06 for z in zs]
        spans, start = [], None
        for i, v in enumerate(on + [False]):
            if v and start is None:
                start = i
            elif not v and start is not None:
                if i - start >= 2:
                    spans.append([start, i - 1])
                start = None
        contacts[key] = spans
    travel = math.dist(root[0][:2], root[-1][:2]) if n > 1 else 0.0
    stem = name or Path(path).stem
    return {"name": stem, "fps": int(round(fps)), "frames": n, "loop": False, "tags": [stem.lower()],
            "category": "mocap", "bones": bones_out, "root": root, "root_normalized": True, "contacts": contacts,
            "stride": round(travel, 4) if travel > 0.05 else None, "source": f"mocap:{Path(path).name}",
            "mapping": mapping, "hip_height_src": round(hip_h, 4)}
