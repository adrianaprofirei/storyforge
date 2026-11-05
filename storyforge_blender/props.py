"""Props: procedural meshes attached to hand sockets (Child Of with keyed influence), with states
hidden / in hand / resting in the world / falling, plus prop-specific animation (map glow,
flashlight beam flicker, gadget LED blink)."""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix

from storyforge_blender import compat, geo
from storyforge_blender.geo import PartMesh, bm_cylinder, bm_rounded_box, bm_sphere, euler

GRIP = {  # local offset/rotation of the prop relative to the hand socket bone
    "map": ((0.0, -0.01, -0.02), (0, 0, 90)), "cup": ((0.0, -0.03, -0.03), (90, 0, 0)),
    "cookie": ((0.0, -0.01, -0.01), (90, 0, 0)), "key": ((0.0, -0.01, -0.01), (0, 0, 0)),
    "flashlight": ((0.0, -0.02, -0.02), (0, 0, 0)), "gadget": ((0.0, -0.02, -0.03), (90, 0, 0)),
    "notebook": ((0.0, -0.02, -0.03), (90, 0, 0)), "book": ((0.0, -0.02, -0.04), (90, 0, 0)),
    "phone": ((0.0, -0.01, -0.02), (90, 0, 0)),
}


def _attr_emission(name: str, color: str, attr: str, strength: float = 5.0):
    """Emission whose strength follows an object custom property (keyable blink / glow)."""
    mat = bpy.data.materials.new(name)
    n = geo.Nodes(mat)
    em = n.node("ShaderNodeEmission")
    em.inputs["Color"].default_value = geo.hex_rgba(color)
    n.link(n.math("MULTIPLY", n.attr(attr), strength), em.inputs["Strength"])
    n.output(em.outputs[0])
    return mat


def _prop_mesh(kind: str, mats, name: str, collection):
    pm = PartMesh(name)
    m = mats
    if kind == "map":
        paper = m.surface("map_paper", "#E9D8A6", "paper")
        pm.add(bm_cylinder(0.022, 0.24, rot=euler(y=90)), "x", paper)
        pm.add(bm_cylinder(0.026, 0.02, center=(0.12, 0, 0), rot=euler(y=90)), "x", m.surface("map_cap", "#6B4226", "wood"))
        pm.add(bm_cylinder(0.026, 0.02, center=(-0.12, 0, 0), rot=euler(y=90)), "x", m.surface("map_cap", "#6B4226", "wood"))
    elif kind == "cup":
        pm.add(bm_cylinder(0.035, 0.08, center=(0, 0, 0.04), radius2=0.04, bevel=0.004), "x",
               m.surface("cup", "#F2F0EA", "plastic"))
        pm.add(bm_cylinder(0.033, 0.005, center=(0, 0, 0.074)), "x", m.surface("cocoa", "#5B3A29", "plastic"))
        pm.add(geo.bm_torus(0.02, 0.006, center=(0.045, 0, 0.04), rot=euler(x=90)), "x", m.surface("cup", "#F2F0EA", "plastic"))
    elif kind == "cookie":
        pm.add(bm_cylinder(0.035, 0.01, bevel=0.003), "x", m.surface("cookie", "#C58B4B", "matte"))
        for i in range(5):
            a = i * 1.3
            pm.add(bm_sphere(0.005, center=(math.cos(a) * 0.018, math.sin(a) * 0.018, 0.005), u=6, v=4), "x",
                   m.surface("chip", "#3B2414", "plastic"))
    elif kind == "key":
        brass = m.surface("key_brass", "#D4A73A", "brass")
        pm.add(geo.bm_torus(0.018, 0.005, rot=euler(x=90)), "x", brass)
        pm.add(bm_rounded_box((0.07, 0.008, 0.008), 0.002, 1, (0.05, 0, 0)), "x", brass)
        pm.add(bm_rounded_box((0.008, 0.008, 0.018), 0.002, 1, (0.075, 0, -0.01)), "x", brass)
        pm.add(bm_rounded_box((0.008, 0.008, 0.012), 0.002, 1, (0.062, 0, -0.008)), "x", brass)
    elif kind == "flashlight":
        body = m.surface("flash_body", "#2B5EA7", "plastic")
        pm.add(bm_cylinder(0.018, 0.12, rot=euler(x=90)), "x", body)
        pm.add(bm_cylinder(0.026, 0.035, center=(0, -0.07, 0), rot=euler(x=90), radius2=0.02), "x",
               m.surface("flash_head", "#C9CED6", "metal"))
        pm.add(bm_cylinder(0.022, 0.004, center=(0, -0.088, 0), rot=euler(x=90)), "x",
               m.surface("flash_lens", "#FFF6D5", "plastic", emission=3.0))
    elif kind == "gadget":
        pm.add(bm_rounded_box((0.07, 0.03, 0.1), 0.008, 2), "x", m.surface("gadget", "#E8B33C", "plastic"))
        pm.add(bm_rounded_box((0.05, 0.005, 0.035), 0.002, 1, (0, -0.016, 0.02)), "x",
               m.surface("gadget_screen", "#7FFFD4", "plastic", emission=1.5))
        pm.add(bm_cylinder(0.003, 0.08, center=(0.025, 0, 0.09)), "x", m.surface("iron", "#2B2A30", "metal"))
        pm.add(bm_sphere(0.008, center=(0.025, 0, 0.13), u=8, v=6), "led", _attr_emission("gadget_led", "#FF3B3B", "led"))
    elif kind in ("notebook", "book"):
        pm.add(bm_rounded_box((0.11, 0.025, 0.15), 0.004, 1), "x",
               m.surface(f"{kind}_cover", "#6C3A8E" if kind == "notebook" else "#8E3B46", "cloth"))
        pm.add(bm_rounded_box((0.1, 0.027, 0.14), 0.002, 1, (0.004, 0, 0)), "x", m.surface("pages", "#F7F1E3", "paper"))
    elif kind == "phone":
        pm.add(bm_rounded_box((0.06, 0.008, 0.12), 0.008, 2), "x", m.surface("phone", "#2B2D42", "plastic"))
        pm.add(bm_rounded_box((0.052, 0.002, 0.105), 0.004, 1, (0, -0.004, 0)), "x",
               m.surface("phone_screen", "#9FD3E6", "plastic", emission=1.2))
    else:  # generic small object
        pm.add(bm_rounded_box((0.06, 0.06, 0.06), 0.012, 2), "x", m.surface("prop", "#5FA8D3", "plastic"))
    return pm.build(collection)


def _flat_map(mats, name: str, collection):
    mat = bpy.data.materials.new("map_flat")
    n = geo.Nodes(mat)
    co = n.texcoord("UV")
    _, v, _ = n.separate(co)
    noise = n.node("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 9.0
    n.link(co, noise.inputs["Vector"])
    ink = n.smooth_step(0.52, 0.5, noise.outputs["Fac"])
    lines = n.math("MULTIPLY", n.smooth_step(0.47, 0.5, noise.outputs["Fac"]), ink)
    base = n.mix_color(n.math("MULTIPLY", lines, 0.6), geo.hex_rgba("#E9D8A6"), geo.hex_rgba("#7A5230"))
    glow_amt = n.attr("glow")
    gold = n.math("MULTIPLY", lines, glow_amt)
    em = n.node("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.75, 0.25, 1)
    strength = n.math("MULTIPLY", gold, 6.0)
    n.link(strength, em.inputs["Strength"])
    surf = n.principled(base, 0.85)
    add = n.node("ShaderNodeAddShader")
    n.link(surf, add.inputs[0])
    n.link(em.outputs[0], add.inputs[1])
    n.output(add.outputs[0])
    del v
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=8, y_segments=6, size=1.0, calc_uvs=True)
    for vtx in bm.verts:
        vtx.co.x *= 0.17
        vtx.co.y *= 0.12
        vtx.co.z = 0.002 * math.sin(vtx.co.x * 30)
    obj = geo.mesh_object(name, bm, collection, [mat], smooth=True)
    obj["glow"] = 0.0
    return obj


def build_props(scene, plan: list[dict], characters: dict, mats, fps: int, frame_start: int, frame_end: int):
    coll = bpy.data.collections.new("PROPS")
    scene.collection.children.link(coll)
    built = {}
    for p in plan:
        obj = _prop_mesh(p["type"], mats, f"PROP_{p['id']}", coll)
        flat = _flat_map(mats, f"PROP_{p['id']}_flat", coll) if p["type"] == "map" else None
        segs = p["segments"]
        con = obj.constraints.new("CHILD_OF")
        con.name = "hand"
        owner = characters.get(p["owner"])
        con.target = owner["rig"] if owner else None
        con.subtarget = "prop.R"
        con.inverse_matrix = Matrix.Identity(4)
        infl, loc, rot, hide = [], [], [], []
        flat_hide = []
        grip_loc, grip_rot = GRIP.get(p["type"], ((0, -0.02, -0.02), (0, 0, 0)))
        for s in segs:
            f = frame_start + int(round(s["t"] * fps))
            if s["state"] == "hand":
                ch = characters.get(s.get("character"))
                if ch is not None:
                    con.target = ch["rig"]  # (single holder per prop in practice; give() switches holder)
                infl.append((f, 1.0))
                loc.append((f, grip_loc))
                rot.append((f, tuple(math.radians(a) for a in grip_rot)))
                hide.append((f, 0.0))
                flat_hide.append((f, 1.0))
            elif s["state"] in ("world", "fall"):
                infl.append((f, 0.0))
                pos = tuple(s.get("pos") or (0, 0, 0))
                if s["state"] == "fall":
                    loc.append((f, pos[:2] + (pos[2] + 0.4,)))
                    loc.append((f + 6, pos))
                    loc.append((f + 9, pos[:2] + (pos[2] + 0.05,)))
                    loc.append((f + 12, pos))
                else:
                    loc.append((f, pos))
                rot.append((f, (0.0, 0.0, 0.3)))
                is_map_flat = flat is not None and s["state"] == "world"
                hide.append((f, 1.0 if is_map_flat else 0.0))
                flat_hide.append((f, 0.0 if is_map_flat else 1.0))
                if flat is not None:
                    flat.location = pos
            else:  # hidden
                infl.append((f, 0.0))
                loc.append((f, (0.0, 0.0, -5.0)))
                rot.append((f, (0.0, 0.0, 0.0)))
                hide.append((f, 1.0))
                flat_hide.append((f, 1.0))
        compat.set_keys(obj, 'constraints["hand"].influence', 0, infl, "CONSTANT")
        compat.set_vector_keys(obj, "location", loc, "CONSTANT")
        compat.set_vector_keys(obj, "rotation_euler", rot, "CONSTANT")
        compat.set_keys(obj, "hide_render", 0, hide, "CONSTANT")
        compat.set_keys(obj, "hide_viewport", 0, hide, "CONSTANT")
        if flat is not None:
            compat.set_keys(flat, "hide_render", 0, flat_hide, "CONSTANT")
            compat.set_keys(flat, "hide_viewport", 0, flat_hide, "CONSTANT")
            if p.get("glow"):
                compat.set_keys(flat, '["glow"]', 0, [(frame_start + int(round(t * fps)), v) for t, v in p["glow"]], "BEZIER")
        if p["type"] == "flashlight":
            spot = bpy.data.lights.new(f"{obj.name}_beam", "SPOT")
            spot.energy = 60.0
            spot.spot_size = math.radians(38)
            spot.spot_blend = 0.4
            spot.color = (1.0, 0.93, 0.78)
            compat.set_props(spot, shadow_soft_size=0.02)
            so = bpy.data.objects.new(f"{obj.name}_beam", spot)
            coll.objects.link(so)
            so.parent = obj
            so.location = (0, -0.09, 0)
            so.rotation_euler = (math.radians(90), 0, 0)
            if p.get("light"):
                compat.set_keys(spot, "energy", 0, [(frame_start + int(round(t * fps)), 60.0 * v) for t, v in p["light"]],
                                "CONSTANT")
        if p["type"] == "gadget":
            led = [(frame_start + k, 1.0 if (k // 6) % 2 == 0 else 0.0) for k in range(0, frame_end - frame_start, 6)]
            obj["led"] = 1.0
            compat.set_keys(obj, '["led"]', 0, led, "CONSTANT")
        built[p["id"]] = obj
    return built
