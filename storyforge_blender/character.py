"""Procedural blocky toy figure: armature (T-pose rest, retarget friendly) + skinned parts.

Everything is generated from the cast registry `look` block so a character is identical in
every episode. Bone names are canonical (see BONES); mocap clips are retargeted onto them.
Face controls (all keyable):
  eyes object custom props: gaze_x, gaze_y, lid_top, lid_bottom, lid_tilt, pupil_scale
  mouth shape keys: mouth_A..mouth_H (Rhubarb visemes), smile, frown, smirk_L, smirk_R,
                    open_shock, tight, wavy
  brows shape keys: brow_up, brow_down, brow_angry, brow_sad, brow_skeptic_L, brow_skeptic_R
  blush object colour alpha (obj.color[3])
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

from storyforge_blender import geo
from storyforge_blender.geo import (
    PartMesh,
    bm_cylinder,
    bm_rounded_box,
    bm_sphere,
    bm_tapered_box,
    euler,
)
from storyforge_blender.materials import MaterialFactory
from storyforge_blender.proportions import body_metrics

# canonical bone -> parent
BONES = {
    "root": None, "hips": "root", "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck",
    "shoulder.L": "chest", "upper_arm.L": "shoulder.L", "forearm.L": "upper_arm.L", "hand.L": "forearm.L",
    "shoulder.R": "chest", "upper_arm.R": "shoulder.R", "forearm.R": "upper_arm.R", "hand.R": "forearm.R",
    "thigh.L": "hips", "shin.L": "thigh.L", "foot.L": "shin.L", "toe.L": "foot.L",
    "thigh.R": "hips", "shin.R": "thigh.R", "foot.R": "shin.R", "toe.R": "foot.R",
}
HELPER_BONES = ["prop.L", "prop.R", "ik_foot.L", "ik_foot.R", "pole_knee.L", "pole_knee.R", "hair_1", "hair_2",
                "backpack", "squash"]
DEFAULT_COLORS = {"skin": "#F2C39B", "top": "#3A7BD5", "top_accent": "#FFFFFF", "bottom": "#2C3E50",
                  "shoes": "#222222", "hair": "#4A2C1A", "eyes": "#2A1A10", "lips": "#B5654A"}

MOUTH_SHAPES = {
    # w: width factor, u: upper opening, d: lower opening (head*0.1 units), c: corner lift, r: roundness
    "X": dict(w=0.78, u=0.0, d=0.0, c=0.16, r=0.0),
    "A": dict(w=0.72, u=0.0, d=0.0, c=0.04, r=0.0),
    "B": dict(w=0.86, u=0.12, d=0.12, c=0.12, r=0.0),
    "C": dict(w=0.92, u=0.24, d=0.38, c=0.1, r=0.0),
    "D": dict(w=0.98, u=0.32, d=0.74, c=0.06, r=0.1),
    "E": dict(w=0.62, u=0.26, d=0.46, c=0.0, r=0.65),
    "F": dict(w=0.42, u=0.16, d=0.24, c=0.0, r=1.0),
    "G": dict(w=0.86, u=0.16, d=0.04, c=0.08, r=0.0),
    "H": dict(w=0.9, u=0.24, d=0.4, c=0.08, r=0.0),
}
EXPRESSION_MOUTH = {
    "smile": dict(c=0.62, w=0.1),
    "frown": dict(c=-0.5, w=-0.05),
    "smirk_L": dict(cl=0.6),
    "smirk_R": dict(cr=0.6),
    "open_shock": dict(u=0.36, d=0.8, w=-0.25, r=0.6),
    "tight": dict(w=-0.3, c=-0.12),
    "wavy": dict(wave=1.0),
}
MOUTH_K = 15


def mouth_points(head: float, params: dict, width_mul: float = 1.0):
    """Top and bottom chains (x, z) for a parametric mouth shape (relative to the mouth centre)."""
    w = params.get("w", 0.78)
    half = 0.30 * head * width_mul * max(0.15, w)
    u = params.get("u", 0.0) * head * 0.1
    d = params.get("d", 0.0) * head * 0.1
    c = params.get("c", 0.0) * head * 0.1
    cl = params.get("cl", 0.0) * head * 0.1
    cr = params.get("cr", 0.0) * head * 0.1
    r = params.get("r", 0.0)
    wave = params.get("wave", 0.0) * head * 0.012
    top, bot = [], []
    for i in range(MOUTH_K):
        s = -1 + 2 * i / (MOUTH_K - 1)
        x = s * half
        prof = (1 - s * s) ** (0.5 + 0.5 * (1 - r)) if abs(s) < 1 else 0.0
        lift = c * s * s + (cl * s * s if s > 0 else 0.0) + (cr * s * s if s < 0 else 0.0)
        wz = wave * math.sin(s * math.pi * 3)
        top.append((x, u * prof + lift + wz))
        bot.append((x, -d * prof + lift + wz))
    return top, bot


def _combine(base: dict, delta: dict) -> dict:
    out = dict(base)
    for k, v in delta.items():
        if k in ("w",):
            out["w"] = base.get("w", 0.78) + v
        else:
            out[k] = base.get(k, 0.0) + v
    return out


def build_mouth_mesh(name: str, head: float, width_mul: float, y: float, z: float, mats, collection):
    """Mouth = interior (UV: v=0 lower .. 1 upper) + constant-thickness lip outline, with shape keys."""
    t = head * 0.014  # lip line half thickness

    def verts_for(params):
        top, bot = mouth_points(head, params, width_mul)
        mid = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(top, bot, strict=False)]
        # outward offsets for the outline
        otop, obot = [], []
        for i in range(MOUTH_K):
            s = -1 + 2 * i / (MOUTH_K - 1)
            i0, i1 = max(0, i - 1), min(MOUTH_K - 1, i + 1)
            tx, tz = top[i1][0] - top[i0][0], top[i1][1] - top[i0][1]
            n = math.hypot(tx, tz) or 1
            nt = (-tz / n, tx / n)
            bx, bz = bot[i1][0] - bot[i0][0], bot[i1][1] - bot[i0][1]
            n2 = math.hypot(bx, bz) or 1
            nb = (bz / n2, -bx / n2)
            corner = abs(s) ** 6
            otop.append((top[i][0] + nt[0] * t + s * corner * t, top[i][1] + nt[1] * t))
            obot.append((bot[i][0] + nb[0] * t + s * corner * t, bot[i][1] + nb[1] * t))
        pts = bot + mid + top + otop + obot
        return [Vector((p[0], y, z + p[1])) for p in pts]

    bm = bmesh.new()
    uv = bm.loops.layers.uv.verify()
    base = verts_for(MOUTH_SHAPES["X"])
    vs = [bm.verts.new(v) for v in base]
    K = MOUTH_K
    B, M, T, OT, OB = (vs[0:K], vs[K:2 * K], vs[2 * K:3 * K], vs[3 * K:4 * K], vs[4 * K:5 * K])
    interior_faces, ring_faces = [], []

    def quad(a, b, c, d, uvs=None, ring=False):
        try:
            f = bm.faces.new((a, b, c, d))
        except ValueError:
            return
        (ring_faces if ring else interior_faces).append(f)
        if uvs:
            for lo, u_ in zip(f.loops, uvs, strict=False):
                lo[uv].uv = u_

    for i in range(K - 1):
        u0, u1 = i / (K - 1), (i + 1) / (K - 1)
        quad(B[i], B[i + 1], M[i + 1], M[i], [(u0, 0), (u1, 0), (u1, 0.5), (u0, 0.5)])
        quad(M[i], M[i + 1], T[i + 1], T[i], [(u0, 0.5), (u1, 0.5), (u1, 1), (u0, 1)])
        quad(T[i], T[i + 1], OT[i + 1], OT[i], ring=True)
        quad(OB[i], OB[i + 1], B[i + 1], B[i], ring=True)
    quad(OB[0], B[0], T[0], OT[0], ring=True)
    quad(B[K - 1], OB[K - 1], OT[K - 1], T[K - 1], ring=True)
    for f in ring_faces:
        f.material_index = 1
    for f in interior_faces:
        f.material_index = 0
    # orient faces toward -Y (the viewer)
    for f in bm.faces:
        f.normal_update()
        if f.normal.y > 0:
            f.normal_flip()
    obj = geo.mesh_object(name, bm, collection, mats, smooth=False)
    obj.shape_key_add(name="Basis", from_mix=False)
    shapes = {f"mouth_{k}": v for k, v in MOUTH_SHAPES.items() if k != "X"}
    for k, delta in EXPRESSION_MOUTH.items():
        shapes[k] = _combine(MOUTH_SHAPES["X"], delta)
    for key_name, params in shapes.items():
        sk = obj.shape_key_add(name=key_name, from_mix=False)
        sk.value = 0.0  # new shape keys may default to 1.0 in recent Blender versions
        sk.slider_min, sk.slider_max = 0.0, 1.0
        for i, co in enumerate(verts_for(params)):
            sk.data[i].co = co
    return obj


def build_brows(name: str, m: dict, ex: float, ez: float, front_y: float, thick_mul: float, mat, collection):
    head = m["head_size"]
    L, H, D = head * 0.24, head * 0.055 * thick_mul, head * 0.03
    bm = bmesh.new()
    for side in (1, -1):
        part = bm_rounded_box((L, D, H), radius=H * 0.45, segments=2,
                              center=(side * ex, front_y - D * 0.3, ez))
        tmp = bpy.data.meshes.new("_b")
        part.to_mesh(tmp)
        part.free()
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    obj = geo.mesh_object(name, bm, collection, [mat])
    obj.shape_key_add(name="Basis", from_mix=False)
    base = [v.co.copy() for v in obj.data.vertices]

    def key(nm, fn):
        sk = obj.shape_key_add(name=nm, from_mix=False)
        sk.value = 0.0
        for i, co in enumerate(base):
            sk.data[i].co = fn(co)

    def inner(co):  # 1 at the inner end (toward the nose), 0 at the outer end
        return max(0.0, min(1.0, 0.5 - (abs(co.x) - ex) / L))

    key("brow_up", lambda co: co + Vector((0, 0, head * 0.07)))
    key("brow_down", lambda co: co + Vector((0, 0, -head * 0.04)))
    key("brow_angry", lambda co: co + Vector((0, 0, head * (0.035 - 0.11 * inner(co)))))
    key("brow_sad", lambda co: co + Vector((0, 0, head * (-0.02 + 0.09 * inner(co)))))
    key("brow_skeptic_L", lambda co: co + Vector((0, 0, head * (0.09 - 0.03 * inner(co)) if co.x > 0 else 0)))
    key("brow_skeptic_R", lambda co: co + Vector((0, 0, head * (0.09 - 0.03 * inner(co)) if co.x < 0 else 0)))
    return obj


def _add_armature_mod(obj, rig, group: str | None = None):
    if group:
        vg = obj.vertex_groups.get(group) or obj.vertex_groups.new(name=group)
        vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    obj.parent = rig
    return mod


def build_armature(name: str, m: dict, collection):
    arm = bpy.data.armatures.new(f"{name}_armature")
    rig = bpy.data.objects.new(f"{name}_rig", arm)
    collection.objects.link(rig)
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    vl.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones
    hz, kz, az = m["hip_z"], m["knee_z"], m["ankle_z"]
    sx, sz = m["shoulder_x"], m["shoulder_z"]
    pos = {
        "root": ((0, 0, 0), (0, 0, 0.12)),
        "hips": ((0, 0, hz), (0, 0, m["torso_base"] + 0.04)),
        "spine": ((0, 0, m["torso_base"] + 0.04), (0, 0, m["chest_z"])),
        "chest": ((0, 0, m["chest_z"]), (0, 0, m["neck_base"])),
        "neck": ((0, 0, m["neck_base"]), (0, 0, m["head_base"])),
        "head": ((0, 0, m["head_base"]), (0, 0, m["head_top"])),
    }
    for side, sg in (("L", 1), ("R", -1)):
        ua, fa, hd = m["upper_arm"], m["forearm"], m["hand"]
        pos[f"shoulder.{side}"] = ((sg * m["torso_w"] * 0.12, 0, sz), (sg * sx, 0, sz))
        pos[f"upper_arm.{side}"] = ((sg * sx, 0, sz), (sg * (sx + ua), 0, sz))
        pos[f"forearm.{side}"] = ((sg * (sx + ua), 0, sz), (sg * (sx + ua + fa), 0, sz))
        pos[f"hand.{side}"] = ((sg * (sx + ua + fa), 0, sz), (sg * (sx + ua + fa + hd), 0, sz))
        hx = sg * m["hip_x"]
        fl = m["foot_length"]
        pos[f"thigh.{side}"] = ((hx, 0, hz), (hx, 0, kz))
        pos[f"shin.{side}"] = ((hx, 0, kz), (hx, 0, az))
        pos[f"foot.{side}"] = ((hx, 0, az), (hx, -fl * 0.55, m["foot_height"] * 0.35))
        pos[f"toe.{side}"] = ((hx, -fl * 0.55, m["foot_height"] * 0.35), (hx, -fl * 0.8, m["foot_height"] * 0.3))
    for bname, parent in BONES.items():
        b = eb.new(bname)
        b.head, b.tail = pos[bname]
        b.roll = 0.0
        if parent:
            b.parent = eb[parent]
            b.use_connect = bname in ("chest", "neck", "head", "forearm.L", "forearm.R", "hand.L", "hand.R",
                                      "shin.L", "shin.R", "foot.L", "foot.R", "toe.L", "toe.R", "spine")
    # helpers (non-deforming)
    for side, sg in (("L", 1), ("R", -1)):
        hand_tip = Vector(pos[f"hand.{side}"][1])
        p = eb.new(f"prop.{side}")
        p.head = hand_tip - Vector((sg * m["hand"] * 0.5, 0, 0))
        p.tail = p.head + Vector((0, 0, -m["limb"]))
        p.parent = eb[f"hand.{side}"]
        ik = eb.new(f"ik_foot.{side}")
        ik.head = Vector(pos[f"foot.{side}"][0])
        ik.tail = ik.head + Vector((0, -m["foot_length"] * 0.5, 0))
        ik.parent = eb["root"]
        pole = eb.new(f"pole_knee.{side}")
        pole.head = Vector((sg * m["hip_x"], -0.6, m["knee_z"]))
        pole.tail = pole.head + Vector((0, -0.08, 0))
        pole.parent = eb["root"]
    h1 = eb.new("hair_1")
    h1.head = Vector((0, m["head_size"] * 0.45, m["head_center"] + m["head_size"] * 0.2))
    h1.tail = h1.head + Vector((0, m["head_size"] * 0.25, -m["head_size"] * 0.25))
    h1.parent = eb["head"]
    h2 = eb.new("hair_2")
    h2.head = h1.tail
    h2.tail = h2.head + Vector((0, m["head_size"] * 0.05, -m["head_size"] * 0.35))
    h2.parent = h1
    h2.use_connect = True
    bp = eb.new("backpack")
    bp.head = Vector((0, m["torso_d"] * 0.5, m["shoulder_z"]))
    bp.tail = bp.head + Vector((0, 0, -m["torso_len"] * 0.6))
    bp.parent = eb["chest"]
    sq = eb.new("squash")
    sq.head = Vector((0, 0, 0))
    sq.tail = Vector((0, 0, 0.08))
    sq.parent = eb["root"]
    for b in eb:
        b.use_deform = b.name not in ("root", "ik_foot.L", "ik_foot.R", "pole_knee.L", "pole_knee.R", "squash",
                                      "prop.L", "prop.R")
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
    arm.display_type = "STICK"
    rig.show_in_front = True
    return rig


def _limb_part(length, thick, center, axis="x", radius_frac=0.42):
    size = {"x": (length, thick, thick), "z": (thick, thick, length)}[axis]
    return bm_rounded_box(size, radius=thick * radius_frac, segments=3, center=center)


def build_hair(style: str, m: dict, mat, accent_mat, collection, rig, hat: bool = False):
    head = m["head_size"]
    hc = m["head_center"]
    hw, hd = head * 0.98, head * 0.92
    pm = PartMesh("hair")
    top_z = hc + head * 0.5
    if style == "bald":
        return None
    if not hat:  # a hat covers the crown; only the hair below the hat line is built
        cap_h = head * 0.2
        cap = bm_rounded_box((hw * 1.06, hd * 1.08, cap_h), radius=head * 0.12, segments=3,
                             center=(0, head * 0.02, top_z - cap_h * 0.32))
        pm.add(cap, "head", mat)
    if style in ("short", "spiky", "ponytail", "bun", "bob", "long", "curly"):
        back = bm_rounded_box((hw * 1.04, head * 0.16, head * 0.55), radius=head * 0.07, segments=2,
                              center=(0, hd * 0.47, hc + head * 0.15))
        pm.add(back, "head", mat)
        for side in (1, -1):
            sideburn = bm_rounded_box((head * 0.12, hd * 0.6, head * 0.32), radius=head * 0.05, segments=2,
                                      center=(side * hw * 0.5, hd * 0.1, hc + head * 0.22))
            pm.add(sideburn, "head", mat)
    if style == "short" and not hat:
        for k in range(4):
            fr = bm_rounded_box((hw * 0.28, head * 0.12, head * 0.12), radius=head * 0.05, segments=2,
                                center=(-hw * 0.36 + k * hw * 0.24, -hd * 0.46, top_z - head * 0.08 - (k % 2) * 0.01),
                                rot=euler(x=-20, z=(k - 1.5) * 6))
            pm.add(fr, "head", mat)
    if style == "spiky":
        spikes = [(-0.3, -0.25, 20, -25), (0.0, -0.3, 0, -30), (0.3, -0.25, -20, -25), (-0.25, 0.1, 25, 10),
                  (0.25, 0.1, -25, 10), (0.0, 0.05, 0, 5), (-0.12, -0.12, 12, -12), (0.14, -0.1, -12, -12)]
        for sx_, sy_, tilt_y, tilt_x in spikes:
            sp = geo.bm_cone(head * 0.17, head * 0.015, head * 0.34,
                             center=(sx_ * hw, sy_ * hd, top_z + head * 0.08),
                             rot=euler(x=tilt_x, y=tilt_y, z=45), segments=4)
            pm.add(sp, "head", mat)
        for k in range(3):
            fr = geo.bm_cone(head * 0.13, head * 0.02, head * 0.22,
                             center=(-hw * 0.25 + k * hw * 0.25, -hd * 0.5, top_z - head * 0.08),
                             rot=euler(x=-125, z=45), segments=4)
            pm.add(fr, "head", mat)
    if style == "ponytail":
        tie = bm_cylinder(head * 0.09, head * 0.08, center=(0, hd * 0.58, hc + head * 0.3), rot=euler(x=90))
        pm.add(tie, "head", accent_mat)
        t1 = bm_rounded_box((head * 0.2, head * 0.2, head * 0.34), radius=head * 0.09, segments=3,
                            center=(0, hd * 0.66, hc + head * 0.12), rot=euler(x=25))
        pm.add(t1, "hair_1", mat)
        t2 = bm_rounded_box((head * 0.17, head * 0.17, head * 0.3), radius=head * 0.08, segments=3,
                            center=(0, hd * 0.74, hc - head * 0.16), rot=euler(x=8))
        pm.add(t2, "hair_2", mat)
        for side in (1, -1):
            fr = bm_rounded_box((hw * 0.5, head * 0.12, head * 0.14), radius=head * 0.06, segments=2,
                                center=(side * hw * 0.24, -hd * 0.46, top_z - head * 0.1), rot=euler(y=side * 12))
            pm.add(fr, "head", mat)
    if style == "bun":
        pm.add(bm_sphere(head * 0.2, center=(0, hd * 0.15, top_z + head * 0.08)), "head", mat)
    if style == "bob":
        for side in (1, -1):
            pm.add(bm_rounded_box((head * 0.16, hd * 1.0, head * 0.7), radius=head * 0.07, segments=2,
                                  center=(side * hw * 0.53, hd * 0.05, hc - head * 0.02)), "head", mat)
    if style == "long":
        pm.add(bm_rounded_box((hw * 1.02, head * 0.15, head * 1.05), radius=head * 0.07, segments=2,
                              center=(0, hd * 0.5, hc - head * 0.2)), "hair_1", mat)
    if style == "curly":
        import random

        rng = random.Random(5)
        for _ in range(16):
            a = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(0.2, 0.48)
            pm.add(bm_sphere(head * rng.uniform(0.12, 0.17),
                             center=(math.cos(a) * r * hw, math.sin(a) * r * hd + head * 0.05,
                                     top_z + head * rng.uniform(-0.02, 0.1)), u=12, v=8), "head", mat)
    obj = pm.build(collection)
    _add_armature_mod(obj, rig)
    return obj


def build_accessory(acc: dict, m: dict, mats: MaterialFactory, collection, rig, colors: dict):
    kind = acc["type"]
    head = m["head_size"]
    hc = m["head_center"]
    hw, hd = head * 0.98, head * 0.92
    color = acc.get("color", "#333333")
    mat = mats.surface(f"acc_{kind}", color, "plastic")
    pm = PartMesh(f"acc_{kind}")
    top_z = hc + head * 0.5
    if kind == "goggles":
        band = bm_rounded_box((hw * 1.08, hd * 1.08, head * 0.08), radius=head * 0.03, segments=2,
                              center=(0, 0.0, top_z - head * 0.2))
        pm.add(band, "head", mat)
        lens_mat = mats.surface("goggle_lens", acc.get("lens", "#7FD3E8"), "glass" if not mats.toon else "plastic")
        for side in (1, -1):
            rim = bm_cylinder(head * 0.13, head * 0.07, center=(side * hw * 0.2, -hd * 0.53, top_z - head * 0.14),
                              rot=euler(x=90 - 15), bevel=head * 0.01)
            pm.add(rim, "head", mat)
            lens = bm_cylinder(head * 0.1, head * 0.08, center=(side * hw * 0.2, -hd * 0.55, top_z - head * 0.14),
                               rot=euler(x=90 - 15))
            pm.add(lens, "head", lens_mat)
    elif kind == "glasses":
        ez = hc + head * 0.03
        for side in (1, -1):
            cx = side * head * 0.22
            for dx, dz, sx_, sz_ in ((0, head * 0.12, head * 0.36, head * 0.035), (0, -head * 0.12, head * 0.36, head * 0.035),
                                     (head * 0.17, 0, head * 0.035, head * 0.27), (-head * 0.17, 0, head * 0.035, head * 0.27)):
                pm.add(bm_rounded_box((sx_, head * 0.03, sz_), radius=head * 0.012, segments=1,
                                      center=(cx + dx, -hd * 0.56, ez + dz)), "head", mat)
            temple = bm_rounded_box((head * 0.03, hd * 0.95, head * 0.03), radius=head * 0.01, segments=1,
                                    center=(side * hw * 0.52, -hd * 0.08, ez + head * 0.1))
            pm.add(temple, "head", mat)
        pm.add(bm_rounded_box((head * 0.1, head * 0.03, head * 0.03), radius=head * 0.01, segments=1,
                              center=(0, -hd * 0.56, ez + head * 0.06)), "head", mat)
    elif kind == "beanie":
        dome = bm_rounded_box((hw * 1.1, hd * 1.12, head * 0.42), radius=head * 0.19, segments=4,
                              center=(0, head * 0.01, top_z - head * 0.02))
        pm.add(dome, "head", mat)
        cuff = bm_rounded_box((hw * 1.12, hd * 1.12, head * 0.14), radius=head * 0.06, segments=2,
                              center=(0, head * 0.01, top_z - head * 0.2))
        pm.add(cuff, "head", mats.surface("beanie_cuff", color, "cloth"))
        pm.add(bm_sphere(head * 0.09, center=(0, 0, top_z + head * 0.24)), "head", mat)
    elif kind == "cap":
        dome = bm_rounded_box((hw * 1.08, hd * 1.1, head * 0.3), radius=head * 0.14, segments=4,
                              center=(0, head * 0.01, top_z + head * 0.02))
        pm.add(dome, "head", mat)
        pm.add(bm_rounded_box((hw * 0.8, hd * 0.55, head * 0.03), radius=head * 0.012, segments=1,
                              center=(0, -hd * 0.62, top_z - head * 0.1), rot=euler(x=-8)), "head", mat)
    elif kind == "backpack":
        tw, td, tl = m["torso_w"], m["torso_d"], m["torso_len"]
        body = bm_rounded_box((tw * 0.82, td * 0.62, tl * 0.82), radius=td * 0.18, segments=3,
                              center=(0, td * 0.5 + td * 0.3, m["torso_base"] + tl * 0.5))
        pm.add(body, "backpack", mat)
        pocket = bm_rounded_box((tw * 0.6, td * 0.2, tl * 0.32), radius=td * 0.07, segments=2,
                                center=(0, td * 0.5 + td * 0.62, m["torso_base"] + tl * 0.3))
        pm.add(pocket, "backpack", mats.surface("backpack_pocket", geo_hex_darken(color, 0.8), "cloth"))
        strap_mat = mats.surface("strap", "#3A3A3A", "cloth")
        for side in (1, -1):
            strap = bm_rounded_box((tw * 0.1, td * 1.12, tl * 0.08), radius=td * 0.03, segments=1,
                                   center=(side * tw * 0.25, 0.0, m["torso_base"] + tl * 0.92))
            pm.add(strap, "chest", strap_mat)
            front = bm_rounded_box((tw * 0.1, td * 0.06, tl * 0.75), radius=td * 0.02, segments=1,
                                   center=(side * tw * 0.25, -td * 0.53, m["torso_base"] + tl * 0.55))
            pm.add(front, "chest", strap_mat)
    elif kind == "headphones":
        pm.add(geo.bm_torus(head * 0.55, head * 0.035, center=(0, 0, hc + head * 0.05), rot=euler(y=90), seg_major=40),
               "head", mat)
        for side in (1, -1):
            pm.add(bm_cylinder(head * 0.15, head * 0.1, center=(side * hw * 0.55, 0, hc), rot=euler(y=90)), "head", mat)
    elif kind == "bowtie":
        for side in (1, -1):
            pm.add(geo.bm_cone(m["limb"] * 0.6, m["limb"] * 0.15, m["limb"] * 0.8,
                               center=(side * m["limb"] * 0.35, -m["torso_d"] * 0.55, m["neck_base"] - 0.01),
                               rot=euler(y=side * 90), segments=4), "chest", mat)
    else:
        return None
    obj = pm.build(collection)
    _add_armature_mod(obj, rig)
    return obj


def geo_hex_darken(h: str, f: float) -> str:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"#{int(r * f):02X}{int(g * f):02X}{int(b * f):02X}"


def build_character(spec: dict, mats: MaterialFactory, scene) -> dict:
    cid = spec["id"]
    look = spec.get("look", {})
    colors = {**DEFAULT_COLORS, **(look.get("colors") or {})}
    clothing = look.get("clothing") or {}
    face_cfg = look.get("face") or {}
    m = body_metrics(look.get("body"))
    coll = bpy.data.collections.new(f"CHR_{cid}")
    scene.collection.children.link(coll)
    rig = build_armature(cid, m, coll)
    rig["sf_character"] = cid

    skin = mats.surface(f"{cid}_skin", colors["skin"], "skin")
    top_style = clothing.get("top", "tshirt")
    top = mats.surface(f"{cid}_top", colors["top"], "cloth", clothing.get("top_pattern", "solid"),
                       colors.get("top_accent"))
    top_plain = mats.surface(f"{cid}_top_plain", colors["top"], "cloth")
    accent = mats.surface(f"{cid}_accent", colors.get("top_accent", "#FFFFFF"), "cloth")
    bottom = mats.surface(f"{cid}_bottom", colors["bottom"], "cloth")
    shoes = mats.surface(f"{cid}_shoes", colors["shoes"], "rubber")
    sole = mats.surface(f"{cid}_sole", "#F2F0EA", "rubber")
    hair_mat = mats.surface(f"{cid}_hair", colors["hair"], "hair")
    lips_mat = mats.lips(f"{cid}_lips", colors.get("lips", "#B5654A"))
    brow_mat = mats.surface(f"{cid}_brow", geo_hex_darken(colors["hair"], 0.75), "hair")

    head = m["head_size"]
    hc = m["head_center"]
    hw, hd = head * 0.98, head * 0.92
    limb = m["limb"]
    tw, td, tl = m["torso_w"], m["torso_d"], m["torso_len"]
    long_sleeves = top_style in ("hoodie", "cardigan", "jacket", "sweater")
    shorts = clothing.get("bottom") == "shorts"

    pm = PartMesh(f"{cid}_body")
    # pelvis + torso (weights split spine/chest)
    pm.add(bm_rounded_box((tw * 0.94, td * 0.96, m["pelvis_h"] * 1.5), radius=td * 0.25, segments=3,
                          center=(0, 0, m["hip_z"] + m["pelvis_h"] * 0.2)), "hips", bottom)
    torso = bm_tapered_box((tw * 0.93, td * 0.98), (tw, td * 1.02), tl, radius=td * 0.26, segments=3,
                           center=(0, 0, m["torso_base"] + tl / 2))
    pm.add(torso, "spine", top, weights={"chest": 0.5})
    pm.add(bm_cylinder(limb * 0.62, m["neck_h"] + head * 0.12, center=(0, 0, m["neck_base"] + m["neck_h"] / 2)),
           "neck", skin)
    pm.add(bm_rounded_box((hw, hd, head), radius=head * 0.2, segments=4, center=(0, 0, hc)), "head", skin)
    if top_style == "hoodie":
        pm.add(bm_rounded_box((tw * 0.7, td * 0.5, tl * 0.3), radius=td * 0.2, segments=3,
                              center=(0, td * 0.48, m["neck_base"] - tl * 0.05)), "chest", top_plain)
        pm.add(bm_rounded_box((tw * 0.62, td * 0.08, tl * 0.26), radius=td * 0.04, segments=2,
                              center=(0, -td * 0.52, m["torso_base"] + tl * 0.22)), "spine", top_plain)
        for side in (1, -1):
            pm.add(bm_cylinder(limb * 0.07, tl * 0.25, center=(side * tw * 0.12, -td * 0.53, m["neck_base"] - tl * 0.15)),
                   "chest", accent)
    if top_style == "cardigan":
        pm.add(bm_rounded_box((tw * 0.34, td * 0.06, tl * 0.98), radius=td * 0.03, segments=2,
                              center=(0, -td * 0.52, m["torso_base"] + tl * 0.5)), "chest", accent)
        for k in range(3):
            pm.add(bm_sphere(limb * 0.1, center=(tw * 0.2, -td * 0.55, m["torso_base"] + tl * (0.25 + 0.22 * k)),
                             u=10, v=6), "chest", mats.surface("button", "#3B2A1A", "plastic"))
    if top_style == "tshirt":
        pm.add(geo.bm_torus(limb * 0.62, limb * 0.12, center=(0, 0, m["neck_base"] - 0.005), seg_major=24, seg_minor=6),
               "chest", accent)
    if clothing.get("top_pattern") == "emblem":
        emb = bm_cylinder(tw * 0.13, td * 0.05, center=(-tw * 0.2, -td * 0.52, m["chest_z"] + tl * 0.08),
                          rot=euler(x=90), segments=8, bevel=0.003)
        pm.add(emb, "chest", accent)
    belt = bm_rounded_box((tw * 0.96, td * 1.0, m["pelvis_h"] * 0.35), radius=td * 0.1, segments=2,
                          center=(0, 0, m["torso_base"] - 0.005))
    pm.add(belt, "hips", mats.surface(f"{cid}_belt", geo_hex_darken(colors["bottom"], 0.6), "rubber"))
    # arms (T-pose along +-X)
    for side, sg in (("L", 1), ("R", -1)):
        sx, sz = m["shoulder_x"], m["shoulder_z"]
        ua, fa, hdn = m["upper_arm"], m["forearm"], m["hand"]
        pm.add(bm_sphere(limb * 0.62, center=(sg * sx, 0, sz), u=16, v=10), f"upper_arm.{side}", top)
        pm.add(_limb_part(ua + limb * 0.35, limb, (sg * (sx + ua / 2), 0, sz)), f"upper_arm.{side}", top)
        pm.add(_limb_part(fa + limb * 0.2, limb * 0.92, (sg * (sx + ua + fa / 2), 0, sz)), f"forearm.{side}",
               top if long_sleeves else skin)
        if long_sleeves:
            pm.add(_limb_part(limb * 0.25, limb * 1.0, (sg * (sx + ua + fa - limb * 0.1), 0, sz), radius_frac=0.3),
                   f"forearm.{side}", accent if top_style == "hoodie" else top_plain)
        hx = sg * (sx + ua + fa + hdn * 0.5)
        pm.add(bm_rounded_box((hdn * 1.05, limb * 1.0, limb * 0.6), radius=limb * 0.25, segments=3,
                              center=(hx, 0, sz)), f"hand.{side}", skin)
        pm.add(bm_rounded_box((hdn * 0.45, limb * 0.32, limb * 0.32), radius=limb * 0.14, segments=2,
                              center=(sg * (sx + ua + fa + hdn * 0.3), -limb * 0.55, sz + limb * 0.05),
                              rot=euler(z=sg * 25)), f"hand.{side}", skin)
        # legs
        lx = sg * m["hip_x"]
        th, sh = m["thigh"], m["shin"]
        pm.add(_limb_part(th + limb * 0.3, limb * 1.18, (lx, 0, m["knee_z"] + th / 2), axis="z"), f"thigh.{side}",
               bottom)
        pm.add(_limb_part(sh + limb * 0.15, limb * 1.08, (lx, 0, m["ankle_z"] + sh / 2), axis="z"), f"shin.{side}",
               skin if shorts else bottom)
        fl, fh = m["foot_length"], m["foot_height"]
        pm.add(bm_rounded_box((limb * 1.32, fl, fh), radius=fh * 0.42, segments=3, center=(lx, -fl * 0.28, fh * 0.55)),
               f"foot.{side}", shoes)
        pm.add(bm_rounded_box((limb * 1.36, fl * 1.02, fh * 0.28), radius=fh * 0.12, segments=2,
                              center=(lx, -fl * 0.28, fh * 0.14)), f"foot.{side}", sole)
    body = pm.build(coll)
    _add_armature_mod(body, rig)

    # ---------------------------------------------------------------- face
    eye_mul = float(face_cfg.get("eye_size", 1.0))
    rx, rz = head * 0.118 * eye_mul, head * 0.148 * eye_mul
    ex, eye_cz = head * 0.215, head * 0.04
    front = -hd / 2
    eyes_mat = mats.eyes(f"{cid}_eyes", colors["skin"], colors.get("eyes", "#2A1A10"), ex, eye_cz, rx, rz)
    ebm = bmesh.new()
    for sg in (1, -1):
        part = bm_sphere(1.0, scale=(rx, rx * 0.42, rz), center=(sg * ex, front, eye_cz), u=28, v=16)
        tmp = bpy.data.meshes.new("_e")
        part.to_mesh(tmp)
        part.free()
        ebm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    eyes = geo.mesh_object(f"{cid}_eyes", ebm, coll, [eyes_mat])
    eyes.location = (0, 0, hc)
    for k, v in {"gaze_x": 0.0, "gaze_y": 0.0, "lid_top": 0.0, "lid_bottom": 0.0, "lid_tilt": 0.0,
                 "pupil_scale": 1.0}.items():
        eyes[k] = v
    _add_armature_mod(eyes, rig, "head")

    mouth = build_mouth_mesh(f"{cid}_mouth", head, float(face_cfg.get("mouth_width", 1.0)), front - head * 0.004,
                             -head * 0.25, [mats.mouth(f"{cid}_mouth_mat", colors.get("lips", "#B5654A"), colors["skin"]),
                                            lips_mat], coll)
    mouth.location = (0, 0, hc)
    _add_armature_mod(mouth, rig, "head")

    brows = build_brows(f"{cid}_brows", m, ex, eye_cz + rz + head * 0.075, front, float(face_cfg.get("brow_thickness", 1.0)),
                        brow_mat, coll)
    brows.location = (0, 0, hc)
    _add_armature_mod(brows, rig, "head")

    bbm = bmesh.new()
    for sg in (1, -1):
        part = bm_sphere(1.0, scale=(head * 0.1, head * 0.01, head * 0.055), center=(sg * head * 0.3, front - 0.002,
                                                                                    -head * 0.13), u=16, v=8)
        tmp = bpy.data.meshes.new("_bl")
        part.to_mesh(tmp)
        part.free()
        bbm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    blush = geo.mesh_object(f"{cid}_blush", bbm, coll, [mats.decal(f"{cid}_blush_mat", "#FF6F91")])
    blush.location = (0, 0, hc)
    blush.color = (1, 1, 1, 0.0)
    _add_armature_mod(blush, rig, "head")
    freckles = None
    if face_cfg.get("freckles"):
        fbm = bmesh.new()
        for sg in (1, -1):
            for dx, dz in ((0.0, 0.0), (0.05, 0.02), (0.025, -0.035), (-0.03, -0.02)):
                part = bm_sphere(head * 0.012, scale=(1, 0.4, 1),
                                 center=(sg * (head * 0.3 + dx * head), front - 0.0015, -head * 0.1 + dz * head), u=8, v=4)
                tmp = bpy.data.meshes.new("_f")
                part.to_mesh(tmp)
                part.free()
                fbm.from_mesh(tmp)
                bpy.data.meshes.remove(tmp)
        freckles = geo.mesh_object(f"{cid}_freckles", fbm, coll,
                                   [mats.surface(f"{cid}_freckle", geo_hex_darken(colors["skin"], 0.72), "skin")])
        freckles.location = (0, 0, hc)
        _add_armature_mod(freckles, rig, "head")

    accessories = [a for a in (look.get("accessories") or []) if isinstance(a, dict)]
    has_hat = any(a["type"] in ("beanie", "cap") for a in accessories)
    hair_style = (look.get("hair") or {}).get("style", "short")
    hair = build_hair(hair_style, m, hair_mat, accent, coll, rig, hat=has_hat)
    acc_objs = [build_accessory(a, m, mats, coll, rig, colors) for a in accessories]
    acc_objs = [a for a in acc_objs if a]
    for o in coll.objects:
        o["sf_character"] = cid
    return {"id": cid, "rig": rig, "body": body, "eyes": eyes, "mouth": mouth, "brows": brows, "blush": blush,
            "freckles": freckles, "hair": hair, "accessories": acc_objs, "collection": coll, "metrics": m,
            "kind": "procedural", "face_mode": "procedural",
            "has_ponytail": hair_style in ("ponytail", "long"),
            "has_backpack": any(a["type"] == "backpack" for a in accessories)}
