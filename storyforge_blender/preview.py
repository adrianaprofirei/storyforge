"""Character preview renders for the cast editor (single still or a small turntable sheet)."""

from __future__ import annotations

import math
from pathlib import Path

import bpy
from mathutils import Vector

from storyforge_blender import compat
from storyforge_blender.animate import key_pose, relaxed_pose, write_keys
from storyforge_blender.character import build_character
from storyforge_blender.materials import MaterialFactory
from storyforge_blender.render_settings import color_management


def _area(scene, name, loc, energy, size, color, target=(0, 0, 0.7)):
    light = bpy.data.lights.new(name, "AREA")
    light.energy = energy
    light.size = size
    light.color = color
    obj = bpy.data.objects.new(name, light)
    scene.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return obj


def render_preview(cast_entry: dict, out: str, style: str = "stylized_3d", turntable: int = 0) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    compat.set_engine(scene, "EEVEE")
    mats = MaterialFactory(style)
    c = build_character(cast_entry, mats, scene)
    keys: dict = {}
    key_pose(c["rig"], relaxed_pose(), 1, keys)
    write_keys(c["rig"], keys)
    m = c["metrics"]
    h = m["total_height"]
    # backdrop: soft studio cyclorama
    bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 1.5, 0))
    floor = bpy.context.active_object
    floor.data.materials.append(mats.surface("cyc", "#2A2D3A", "matte"))
    world = bpy.data.worlds.new("w")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.03, 0.035, 0.05, 1)
    _area(scene, "key", (-1.6, -2.2, h * 1.6), 260, 1.4, (1, 0.94, 0.86), (0, 0, h * 0.6))
    _area(scene, "fill", (2.0, -1.8, h * 0.9), 90, 2.4, (0.82, 0.9, 1.0), (0, 0, h * 0.6))
    _area(scene, "rim", (0.8, 2.0, h * 1.8), 280, 0.8, (1, 0.95, 0.9), (0, 0, h * 0.7))
    cd = bpy.data.cameras.new("cam")
    cd.sensor_fit = "VERTICAL"
    cd.sensor_height = 36
    cd.lens = 50
    cam = bpy.data.objects.new("cam", cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    dist = (h * 1.35 / 2) / math.tan(math.atan(18 / 50))
    target = Vector((0, 0, h * 0.52))
    scene.render.resolution_x, scene.render.resolution_y = 540, 960
    color_management(scene, style)
    compat.set_props(scene.eevee, taa_render_samples=16)
    views = [0] if turntable <= 1 else [i * 360 / turntable for i in range(turntable)]
    outs = []
    for i, ang in enumerate(views):
        a = math.radians(ang)
        cam.location = target + Vector((math.sin(a) * dist, -math.cos(a) * dist, h * 0.05))
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        path = out if len(views) == 1 else str(Path(out).with_name(f"{Path(out).stem}_{i:02d}.png"))
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        outs.append(path)
    print(f"SF_LOG preview written: {', '.join(outs)}", flush=True)
