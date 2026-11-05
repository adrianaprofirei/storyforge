"""Emotion FX meshes, bone-parented to the character's head and timed to beats.

Every FX pops in with an overshoot (scale 0 -> 1.15 -> 1), has a small idle motion while active
(slide, pulse, bob, twinkle) and pops out; outside its window it is hidden from rendering.
Head bone space: the head bone points up (+Y local = world up), local +X = character's left,
local +Z = the face direction, and children are placed relative to the head *top* (bone tail).
"""

from __future__ import annotations

import math

import bmesh
import bpy

from storyforge_blender import compat, geo
from storyforge_blender.geo import bm_cylinder, bm_rounded_box, bm_sphere, euler

COLORS = {"sweat_drop": "#8FD3FF", "tears": "#7FC8FF", "anger_mark": "#E8343A", "sparkles": "#FFE45C",
          "question_mark": "#FFD447", "exclamation_mark": "#FF5A3C", "shock_lines": "#FFFFFF", "lightbulb": "#FFF2A8"}


def _text_mesh(char: str, size: float, depth: float, name: str):
    cu = bpy.data.curves.new(f"{name}_curve", "FONT")
    cu.body = char
    cu.size = size
    cu.extrude = depth
    cu.bevel_depth = depth * 0.35
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    tmp = bpy.data.objects.new(f"{name}_tmp", cu)
    bpy.context.scene.collection.objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    return me


def _mesh_for(kind: str, head: float, mats, name: str):
    """Return (mesh data, material) in head-local units (built facing +Z = the face direction)."""
    mat = mats.surface(f"fx_{kind}", COLORS[kind], "plastic", emission=2.5 if kind in ("sparkles", "lightbulb", "shock_lines") else 0.0)
    if kind in ("question_mark", "exclamation_mark"):
        me = _text_mesh("?" if kind == "question_mark" else "!", head * 0.55, head * 0.06, name)
        me.materials.append(mat)
        return me
    bm = bmesh.new()
    if kind == "sweat_drop":
        d = bm_sphere(head * 0.07, scale=(0.8, 1.0, 0.55), u=16, v=10)
        for v in d.verts:
            if v.co.y > 0:
                v.co.x *= max(0.05, 1 - v.co.y / (head * 0.07) * 0.95)
                v.co.z *= max(0.05, 1 - v.co.y / (head * 0.07) * 0.95)
                v.co.y *= 1.8
        geo_append(bm, d)
    elif kind == "tears":
        for side in (1, -1):
            for k in range(3):
                d = bm_sphere(head * 0.035, scale=(0.7, 1.4, 0.6), center=(side * head * 0.215, -k * head * 0.12, 0), u=10, v=6)
                geo_append(bm, d)
    elif kind == "anger_mark":
        for k in range(4):
            a = math.radians(45 + 90 * k)
            seg = bm_rounded_box((head * 0.05, head * 0.16, head * 0.04), head * 0.015, 2,
                                 center=(math.cos(a) * head * 0.07, math.sin(a) * head * 0.07, 0),
                                 rot=euler(z=math.degrees(a) + 90))
            geo_append(bm, seg)
    elif kind == "sparkles":
        for dx, dy, s in ((-0.55, 0.15, 1.0), (0.6, 0.3, 0.8), (-0.35, 0.55, 0.6), (0.4, -0.1, 0.7),
                         (0.05, 0.62, 0.5)):
            for axis in ("x", "y"):
                r = euler(z=45 if axis == "x" else -45)
                spike = bm_rounded_box((head * 0.02 * s, head * 0.16 * s, head * 0.02 * s), head * 0.006, 1,
                                       center=(dx * head, dy * head, 0), rot=r)
                geo_append(bm, spike)
            geo_append(bm, bm_sphere(head * 0.025 * s, center=(dx * head, dy * head, 0), u=8, v=6))
    elif kind == "shock_lines":
        for k in range(10):
            a = 2 * math.pi * k / 10
            ln = bm_rounded_box((head * 0.025, head * 0.17, head * 0.02), head * 0.008, 1,
                                center=(math.cos(a) * head * 0.62, math.sin(a) * head * 0.62, 0),
                                rot=euler(z=math.degrees(a) - 90))
            geo_append(bm, ln)
    elif kind == "lightbulb":
        geo_append(bm, bm_sphere(head * 0.11, center=(0, head * 0.06, 0), u=16, v=10))
        geo_append(bm, bm_cylinder(head * 0.055, head * 0.07, center=(0, -head * 0.06, 0), rot=euler(x=90)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    geo.shade_smooth(me, 45)
    return me


def geo_append(dst, src):
    tmp = bpy.data.meshes.new("_fx")
    src.to_mesh(tmp)
    src.free()
    dst.from_mesh(tmp)
    bpy.data.meshes.remove(tmp)


# placement relative to the head top in head-bone local axes (x: left, y: up, z: face direction)
PLACEMENT = {
    "sweat_drop": (0.52, -0.22, 0.25), "tears": (0.0, -0.55, 0.5), "anger_mark": (0.42, 0.02, 0.2),
    "sparkles": (0.0, -0.35, 0.3), "question_mark": (0.35, 0.32, 0.1), "exclamation_mark": (0.3, 0.32, 0.1),
    "shock_lines": (0.0, -0.5, 0.0), "lightbulb": (0.0, 0.38, 0.05),
}


def build_fx(scene, spec: dict, characters: dict, mats) -> int:
    events = spec.get("fx", [])
    if not events:
        return 0
    coll = bpy.data.collections.new("FX")
    scene.collection.children.link(coll)
    count = 0
    for i, e in enumerate(events):
        c = characters.get(e["character"])
        if c is None or e["type"] not in PLACEMENT:
            continue
        head = c["metrics"]["head_size"]
        name = f"FX_{e['character']}_{e['type']}_{i}"
        me = _mesh_for(e["type"], head, mats, name)
        obj = bpy.data.objects.new(name, me)
        coll.objects.link(obj)
        obj.parent = c["rig"]
        obj.parent_type = "BONE"
        obj.parent_bone = "head"
        px, py, pz = PLACEMENT[e["type"]]
        base = (px * head, py * head, pz * head)
        obj.location = base
        f0, f1 = int(e["frame"]), int(e["end_frame"])
        pop = 4
        s = 1.0 + 0.15 * float(e.get("intensity", 0.5))
        scale_keys = [(f0 - 1, 0.0), (f0, 0.01), (f0 + pop, s * 1.15), (f0 + pop + 3, s), (f1 - 3, s), (f1, 0.0)]
        if e["type"] == "anger_mark":  # pulse
            scale_keys = [(f0 - 1, 0.0), (f0, 0.01), (f0 + pop, s * 1.2)]
            f = f0 + pop
            while f < f1 - 6:
                scale_keys += [(f + 3, s * 0.85), (f + 6, s * 1.15)]
                f += 6
            scale_keys += [(f1, 0.0)]
        for axis in range(3):
            compat.set_keys(obj, "scale", axis, scale_keys, "BEZIER")
        if e["type"] in ("sweat_drop", "tears"):
            compat.set_keys(obj, "location", 1, [(f0, base[1]), (f1, base[1] - head * (0.18 if e["type"] == "sweat_drop" else 0.25))],
                            "LINEAR")
        elif e["type"] in ("question_mark", "exclamation_mark", "lightbulb"):
            bob = [(f, base[1] + head * 0.03 * math.sin((f - f0) / 5.0)) for f in range(f0, f1 + 1, 3)]
            compat.set_keys(obj, "location", 1, bob, "BEZIER")
        elif e["type"] == "sparkles":
            spin = [(f0, 0.0), (f1, math.radians(40))]
            compat.set_keys(obj, "rotation_euler", 2, spin, "LINEAR")
        elif e["type"] == "shock_lines":
            flash = []
            for f in range(f0, f1, 4):
                flash += [(f, s), (f + 2, s * 1.12)]
            compat.set_keys(obj, "scale", 0, scale_keys[:3] + flash + [(f1, 0.0)], "LINEAR")
            compat.set_keys(obj, "scale", 1, scale_keys[:3] + flash + [(f1, 0.0)], "LINEAR")
        hide = [(f0 - 2, 1.0), (f0 - 1, 0.0), (f1 + 1, 1.0)]
        compat.set_keys(obj, "hide_render", 0, hide, "CONSTANT")
        compat.set_keys(obj, "hide_viewport", 0, hide, "CONSTANT")
        obj.hide_render = True
        count += 1
    return count
