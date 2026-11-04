"""Custom rigged characters (.blend / .fbx / .glb / .gltf).

`inspect_character(path)` reports the armature, an automatic canonical bone map, missing bones,
face shape keys (ARKit / VRM / Oculus viseme conventions detected) and the height, so the cast
registry entry can be created (UI: Cast -> Import character).

At scene build, `load_imported(spec)` brings the character in and drives it from a hidden
*canonical proxy rig* that receives exactly the same animation as procedural characters (NLA
layers, foot locking, collision fixes, secondary motion). After all passes, `bake_from_proxy`
converts the proxy's world-space rotations onto the custom bones every frame:
    D = R_pose @ R_rest^-1 (proxy), B = rest-direction alignment canonical -> custom,
    D_custom = D @ B^-1,  local basis = R_rest^-1 @ D_parent^-1 @ D_custom @ R_rest (custom).
"""

from __future__ import annotations

from pathlib import Path

import addon_utils
import bpy
from mathutils import Quaternion, Vector

from storyforge_blender import compat
from storyforge_blender.bonemap import CANONICAL, CANONICAL_PARENT, REST_DIR, auto_map, missing_required

FACE_PRESETS = {
    "arkit": ["jawOpen", "mouthClose", "eyeBlinkLeft", "eyeBlinkRight", "mouthSmileLeft", "browInnerUp"],
    "vrm": ["A", "I", "U", "E", "O", "Blink", "Joy", "Angry", "Sorrow", "Fun"],
    "oculus": ["viseme_aa", "viseme_PP", "viseme_FF", "viseme_sil", "viseme_O"],
}


def _enable(mod):
    try:
        addon_utils.enable(mod, default_set=True)
    except Exception:
        pass


def import_file(path: str, collection=None) -> list:
    ext = Path(path).suffix.lower()
    before = set(bpy.data.objects)
    if ext == ".fbx":
        _enable("io_scene_fbx")
        bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=False, ignore_leaf_bones=True)
    elif ext in (".glb", ".gltf"):
        _enable("io_scene_gltf2")
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".blend":
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        for o in dst.objects:
            if o is not None:
                (collection or bpy.context.scene.collection).objects.link(o)
    else:
        raise ValueError(f"unsupported character file: {path}")
    new = [o for o in bpy.data.objects if o not in before]
    if collection is not None and ext != ".blend":
        for o in new:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            collection.objects.link(o)
    return new


def _shape_keys(objs) -> list[str]:
    names = set()
    for o in objs:
        if o.type == "MESH" and o.data.shape_keys:
            names |= {k.name for k in o.data.shape_keys.key_blocks}
    return sorted(names)


def detect_face_preset(keys: list[str]) -> str | None:
    best, score = None, 0
    for name, sig in FACE_PRESETS.items():
        s = sum(1 for k in sig if k in keys)
        if s > score:
            best, score = name, s
    return best if score >= 2 else None


def inspect_character(path: str) -> dict:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objs = import_file(path)
    arms = [o for o in objs if o.type == "ARMATURE"]
    if not arms:
        return {"ok": False, "error": "no armature found"}
    arm = max(arms, key=lambda a: len(a.data.bones))
    names = [b.name for b in arm.data.bones]
    mapping = auto_map(names)
    meshes = [o for o in objs if o.type == "MESH"]
    zs = [(o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box] or [0.0, 1.0]
    keys = _shape_keys(meshes)
    return {"ok": not missing_required(mapping), "armature": arm.name, "bones": names, "bone_map": mapping,
            "missing": missing_required(mapping), "meshes": [o.name for o in meshes], "shape_keys": keys,
            "face_preset": detect_face_preset(keys), "height": round(max(zs) - min(zs), 4)}


def load_imported(cs: dict, scene, proxy_metrics: dict) -> dict:
    """Import the custom character, scale it to the cast height, return handles incl. the armature."""
    imp = cs.get("import") or {}
    coll = bpy.data.collections.new(f"CHR_{cs['id']}_imported")
    scene.collection.children.link(coll)
    objs = import_file(imp["file"], coll)
    arms = [o for o in objs if o.type == "ARMATURE"]
    arm = max(arms, key=lambda a: len(a.data.bones))
    meshes = [o for o in objs if o.type == "MESH"]
    zs = [(o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box] or [0.0, 1.0]
    height = max(zs) - min(zs)
    target = float(imp.get("height") or proxy_metrics["total_height"])
    s = float(imp.get("scale") or (target / height if height > 1e-4 else 1.0))
    root_objs = [o for o in objs if o.parent is None]
    for o in root_objs:
        o.scale = (o.scale[0] * s, o.scale[1] * s, o.scale[2] * s)
    bpy.context.view_layer.update()
    mapping = dict(auto_map([b.name for b in arm.data.bones]))
    mapping.update({k: v for k, v in (imp.get("bone_map") or {}).items() if v in arm.pose.bones})
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    face_mesh = next((o for o in meshes if o.data.shape_keys), None)
    return {"armature": arm, "objects": objs, "meshes": meshes, "mapping": mapping, "collection": coll,
            "face_mesh": face_mesh, "root_objects": root_objs, "scale": s}


def bake_from_proxy(scene, proxy, imported: dict, frame_start: int, frame_end: int):
    arm = imported["armature"]
    mapping = imported["mapping"]
    mw_p = proxy.matrix_world
    # rest data
    p_rest = {c: (mw_p @ proxy.data.bones[c].matrix_local).to_quaternion() for c in CANONICAL if c in proxy.data.bones}
    c_rest_local = {c: arm.data.bones[s].matrix_local.to_quaternion() for c, s in mapping.items()}
    align = {}
    for c, sname in mapping.items():
        b = arm.data.bones[sname]
        d = (arm.matrix_world.to_3x3() @ (b.tail_local - b.head_local))
        if d.length < 1e-6:
            align[c] = Quaternion()
            continue
        align[c] = Vector(REST_DIR[c]).normalized().rotation_difference(d.normalized())
    # follow the proxy's root transform
    for o in imported["root_objects"]:
        con = o.constraints.new("COPY_TRANSFORMS")
        con.target = proxy
        compat.set_props(con, mix_mode="BEFORE_FULL")  # keep the import scale under the proxy transform
    keys = {s: [[], [], [], []] for s in mapping.values()}
    hip_keys = [[], [], []]
    hips_src = mapping.get("hips")
    for f in range(frame_start, frame_end + 1):
        scene.frame_set(f)
        D = {}
        for c in CANONICAL:
            if c in p_rest:
                q_pose = (mw_p @ proxy.pose.bones[c].matrix).to_quaternion()
                D[c] = q_pose @ p_rest[c].inverted()
            else:
                D[c] = D.get(CANONICAL_PARENT[c] or "", Quaternion())
        Dc = {c: D[c] @ align[c].inverted() for c in mapping}
        for c, sname in mapping.items():
            parent = CANONICAL_PARENT[c]
            while parent is not None and parent not in mapping:
                parent = CANONICAL_PARENT[parent]
            dp = Dc[parent] if parent else Quaternion()
            r = c_rest_local[c]
            basis = r.inverted() @ dp.inverted() @ Dc[c] @ r
            seq = keys[sname]
            if seq[0] and (seq[0][-1][1] * basis.w + seq[1][-1][1] * basis.x + seq[2][-1][1] * basis.y +
                           seq[3][-1][1] * basis.z) < 0:
                basis.negate()
            for k in range(4):
                seq[k].append((float(f), basis[k]))
        if hips_src:
            off = proxy.pose.bones["hips"].location
            r3 = arm.data.bones[hips_src].matrix_local.to_3x3().inverted() @ proxy.data.bones["hips"].matrix_local.to_3x3()
            loc = r3 @ off / max(1e-4, imported["scale"])
            for k in range(3):
                hip_keys[k].append((float(f), loc[k]))
    for sname, seq in keys.items():
        for k in range(4):
            compat.set_keys(arm, f'pose.bones["{sname}"].rotation_quaternion', k, seq[k], "LINEAR", group=sname)
    if hips_src:
        for k in range(3):
            compat.set_keys(arm, f'pose.bones["{hips_src}"].location', k, hip_keys[k], "LINEAR", group=hips_src)
    # hide the proxy from renders (it only drives)
    proxy.hide_render = True
    for ch in proxy.children:
        ch.hide_render = True
    return len(keys)
