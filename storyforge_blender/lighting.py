"""World, sun/moon, volumetrics and the per-shot three-point rig (keyed per shot)."""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

from storyforge_blender import compat
from storyforge_blender.geo import hex_rgba


def _aim(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def build_world(scene, base: dict):
    world = bpy.data.worlds.new("SF_World")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    grad = nt.nodes.new("ShaderNodeTexGradient")
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    mr = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs[2], mr.inputs["Value"])
    mr.inputs["From Min"].default_value = 0.4
    mr.inputs["From Max"].default_value = 0.8
    nt.links.new(mr.outputs["Result"], mix.inputs["Factor"])
    mix.inputs[6].default_value = hex_rgba(base["world"]["bottom"])
    mix.inputs[7].default_value = hex_rgba(base["world"]["top"])
    nt.links.new(mix.outputs[2], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = base["world"]["strength"]
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    del grad
    vol = base.get("volumetrics")
    if vol:
        pv = nt.nodes.new("ShaderNodeVolumePrincipled")
        pv.inputs["Density"].default_value = vol["density"]
        pv.inputs["Anisotropy"].default_value = vol["anisotropy"]
        pv.inputs["Color"].default_value = (*vol["color"], 1.0)
        nt.links.new(pv.outputs[0], out.inputs["Volume"])
    return world


def build_sun(scene, base: dict, collection):
    s = base.get("sun")
    if not s or s["strength"] <= 0:
        return None
    light = bpy.data.lights.new("SF_Sun", "SUN")
    light.energy = s["strength"]
    light.color = s["color"]
    light.angle = math.radians(s.get("angle", 2.0))
    obj = bpy.data.objects.new("SF_Sun", light)
    collection.objects.link(obj)
    az, el = math.radians(s["azimuth"]), math.radians(s["elevation"])
    # light comes FROM azimuth/elevation (az 0 = from the audience side -Y)
    direction = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    obj.location = direction * 10
    _aim(obj, (0, 0, 0))
    return obj


def build_shot_rig(scene, rigs: list[dict], characters_coll, collection, light_linking: bool = True,
                   style: str = "stylized_3d"):
    """One key/fill/rim set; transforms, energies and colours keyed (CONSTANT) at each shot start."""
    objs = {}
    for role in ("key", "fill", "rim"):
        light = bpy.data.lights.new(f"SF_{role}", "AREA")
        light.shape = "DISK" if role != "fill" else "RECTANGLE"
        compat.set_props(light, use_shadow=role != "fill", shadow_soft_size=0.25)
        if role == "fill":
            compat.set_props(light, use_shadow=True)
        obj = bpy.data.objects.new(f"SF_{role}", light)
        collection.objects.link(obj)
        objs[role] = obj
    if light_linking and characters_coll is not None and hasattr(objs["rim"], "light_linking"):
        try:
            objs["rim"].light_linking.receiver_collection = characters_coll
        except Exception:
            pass
    for role, obj in objs.items():
        lkeys, rkeys, ekeys, ckeys, skeys = [], [], [], [], []
        for r in rigs:
            spec = r["rig"][role]
            f = r["frame"]
            obj.location = spec["position"]
            _aim(obj, spec["target"])
            lkeys.append((f, tuple(obj.location)))
            rkeys.append((f, tuple(obj.rotation_euler)))
            toon = style == "cartoon"
            # cel shading wants crisp, designed shadow shapes: small sources, a touch more energy
            ekeys.append((f, spec["energy"] * (0.8 if toon and role == "fill" else 1.0)))
            ckeys.append((f, tuple(spec["color"])))
            skeys.append((f, spec["size"] * (0.12 if toon and role != "fill" else 1.0)))
        compat.set_vector_keys(obj, "location", lkeys, "CONSTANT")
        compat.set_vector_keys(obj, "rotation_euler", rkeys, "CONSTANT")
        compat.set_keys(obj.data, "energy", 0, ekeys, "CONSTANT")
        compat.set_vector_keys(obj.data, "color", ckeys, "CONSTANT")
        compat.set_keys(obj.data, "size", 0, skeys, "CONSTANT")
    return objs
