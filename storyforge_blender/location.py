"""Procedural sets for the location presets (deterministic, seeded)."""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from storyforge_blender import geo
from storyforge_blender.geo import Nodes, bm_cylinder, bm_rounded_box, bm_sphere, euler, hex_rgba
from storyforge_blender.locations_data import get_location
from storyforge_blender.materials import MaterialFactory

BOOK_COLORS = ["#8E3B46", "#2E5E4E", "#1F4E79", "#C9A227", "#6B4E71", "#B5651D", "#3D6B8C", "#7A2E2E",
               "#556B2F", "#D2B48C", "#4B3F72", "#A0522D", "#2F4F4F", "#C06C84"]


class SetBuilder:
    def __init__(self, scene, mats: MaterialFactory, preset: str, time_of_day: str, seed: int = 11):
        self.scene = scene
        self.mats = mats
        self.loc = get_location(preset)
        self.preset = self.loc["preset"]
        self.tod = time_of_day
        self.rng = random.Random(seed)
        self.coll = bpy.data.collections.new("SET")
        scene.collection.children.link(self.coll)
        self.pal = self.loc["palette"]
        self.objects: dict[str, object] = {}
        self.anim_targets: dict[str, list] = {}

    # ------------------------------------------------------------------ materials
    def wood(self, name: str, color: str, planks: bool = True, scale: float = 1.0):
        key = ("wood", name, color, planks, scale, self.mats.style)
        if key in self.mats.cache:
            return self.mats.cache[key]
        if self.mats.toon or not planks:
            mat = self.mats.surface(name, color, "wood")
            self.mats.cache[key] = mat
            return mat
        mat = bpy.data.materials.new(name)
        n = Nodes(mat)
        co = n.texcoord("Object")
        mapping = n.node("ShaderNodeMapping")
        n.link(co, mapping.inputs["Vector"])
        mapping.inputs["Scale"].default_value = (1.0 * scale, 6.0 * scale, 1.0 * scale)
        brick = n.node("ShaderNodeTexBrick")
        n.link(mapping.outputs[0], brick.inputs["Vector"])
        base = hex_rgba(color)
        brick.inputs["Color1"].default_value = base
        brick.inputs["Color2"].default_value = geo.scale_rgba(base, 0.82)
        brick.inputs["Mortar"].default_value = geo.scale_rgba(base, 0.45)
        brick.inputs["Scale"].default_value = 1.6
        brick.inputs["Mortar Size"].default_value = 0.008
        brick.inputs["Brick Width"].default_value = 1.2
        brick.inputs["Row Height"].default_value = 0.12
        noise = n.node("ShaderNodeTexNoise")
        n.link(co, noise.inputs["Vector"])
        noise.inputs["Scale"].default_value = 40.0
        noise.inputs["Detail"].default_value = 6.0
        grain = n.math("MULTIPLY", noise.outputs["Fac"], 0.25)
        col = n.mix_color(grain, brick.outputs["Color"], geo.scale_rgba(base, 0.6))
        bump = n.node("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.15
        n.link(brick.outputs["Fac"], bump.inputs["Height"])
        sh = n.principled(col, 0.55, Specular_IOR_Level=0.45, Coat_Weight=0.15, Coat_Roughness=0.3)
        bsdf = sh.node
        n.link(bump.outputs["Normal"], bsdf.inputs["Normal"])
        n.output(sh)
        self.mats.cache[key] = mat
        return mat

    def stone(self, name: str, color: str):
        key = ("stone", name, color, self.mats.style)
        if key in self.mats.cache:
            return self.mats.cache[key]
        if self.mats.toon:
            mat = self.mats.surface(name, color, "matte")
        else:
            mat = bpy.data.materials.new(name)
            n = Nodes(mat)
            co = n.texcoord("Object")
            brick = n.node("ShaderNodeTexBrick")
            n.link(co, brick.inputs["Vector"])
            base = hex_rgba(color)
            brick.inputs["Color1"].default_value = base
            brick.inputs["Color2"].default_value = geo.scale_rgba(base, 0.85)
            brick.inputs["Mortar"].default_value = geo.scale_rgba(base, 0.55)
            brick.inputs["Scale"].default_value = 2.2
            brick.inputs["Mortar Size"].default_value = 0.015
            bump = n.node("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.3
            n.link(brick.outputs["Fac"], bump.inputs["Height"])
            sh = n.principled(brick.outputs["Color"], 0.85, Specular_IOR_Level=0.3)
            n.link(bump.outputs["Normal"], sh.node.inputs["Normal"])
            n.output(sh)
        self.mats.cache[key] = mat
        return mat

    def obj(self, name: str, bm, mats, smooth: bool = True):
        o = geo.mesh_object(name, bm, self.coll, mats if isinstance(mats, (list, tuple)) else [mats], smooth=smooth)
        self.objects[name] = o
        return o

    # ------------------------------------------------------------------ shared pieces
    def floor(self, mat, size=None):
        b = self.loc["bounds"]
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
        w, d = (b[1] - b[0]) * 1.6, (b[3] - b[2]) * 1.6
        for v in bm.verts:
            v.co.x = v.co.x * w / 2 + (b[0] + b[1]) / 2
            v.co.y = v.co.y * d / 2 + (b[2] + b[3]) / 2
        return self.obj("floor", bm, mat, smooth=False)

    def wall(self, name: str, x0, y0, x1, y1, h, mat, thickness=0.12, z0=0.0):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        length = math.hypot(x1 - x0, y1 - y0)
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
        bm = bm_rounded_box((length, thickness, h), radius=0.0, segments=0, center=(0, 0, 0))
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=euler(z=ang), verts=bm.verts)
        bmesh.ops.translate(bm, vec=Vector((cx, cy, z0 + h / 2)), verts=bm.verts)
        return self.obj(name, bm, mat, smooth=False)

    def books_shelf(self, name: str, x: float, y: float, width: float, height: float, depth: float, rot_z: float = 0.0):
        frame_mat = self.wood(f"{name}_wood", self.pal["trim"], planks=False)
        pm = geo.PartMesh(name)
        t = 0.04
        for sx in (-1, 1):
            pm.add(bm_rounded_box((t, depth, height), 0.008, 1, (sx * (width / 2 - t / 2), 0, height / 2)), "x", frame_mat)
        pm.add(bm_rounded_box((width, t, height), 0.0, 0, (0, depth / 2 - t / 2, height / 2)), "x", frame_mat)
        shelves = 5
        book_mats = [self.mats.surface(f"book_{c}", c, "paper" if self.rng.random() < 0.5 else "cloth") for c in BOOK_COLORS]
        for k in range(shelves + 1):
            z = 0.06 + k * (height - 0.1) / shelves
            pm.add(bm_rounded_box((width, depth, t), 0.006, 1, (0, 0, z)), "x", frame_mat)
            if k == shelves:
                continue
            bx = -width / 2 + t + 0.01
            space = (height - 0.1) / shelves - t
            while bx < width / 2 - t - 0.05:
                bw = self.rng.uniform(0.03, 0.065)
                bh = space * self.rng.uniform(0.62, 0.9)
                lean = self.rng.random() < 0.07
                book = bm_rounded_box((bw, depth * self.rng.uniform(0.65, 0.85), bh), radius=0.004, segments=1,
                                      center=(bx + bw / 2, -depth * 0.05, z + t / 2 + bh / 2),
                                      rot=euler(y=self.rng.uniform(8, 15)) if lean else None)
                pm.add(book, "x", self.rng.choice(book_mats))
                bx += bw + (0.03 if lean else 0.002)
                if self.rng.random() < 0.05:
                    bx += self.rng.uniform(0.04, 0.12)
        o = pm.build(self.coll)
        o.location = (x, y, 0)
        o.rotation_euler = (0, 0, math.radians(rot_z))
        self.objects[name] = o
        return o

    def window_view(self, name: str, x, y, z, w, h, sky_top, sky_bottom, strength=1.0, tower: bool = True,
                    stars: bool = False, rot_z: float = 0.0):
        mat = bpy.data.materials.new(f"{name}_sky")
        n = Nodes(mat)
        co = n.texcoord("Generated")
        _, gy, gz = n.separate(co)
        col = n.mix_color(gz, hex_rgba(sky_bottom), hex_rgba(sky_top))
        if stars:
            vor = n.node("ShaderNodeTexVoronoi")
            vor.inputs["Scale"].default_value = 60.0
            n.link(co, vor.inputs["Vector"])
            st = n.smooth_step(0.05, 0.02, vor.outputs["Distance"])
            col = n.mix_color(n.math("MULTIPLY", st, 0.9), col, (1, 1, 1, 1))
        em = n.node("ShaderNodeEmission")
        n._in(em, "Color", col)
        em.inputs["Strength"].default_value = strength
        n.output(em.outputs[0])
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
        for v in bm.verts:
            v.co = Vector((v.co.x * w * 1.8, 0.0, v.co.y * h * 1.8 + h * 0.2))
        o = self.obj(name, bm, mat, smooth=False)
        o.location = (x, y + 1.4, z)
        o.rotation_euler = (0, 0, math.radians(rot_z))
        if tower:
            tm = self.mats.surface("tower_far", "#2A2638" if self.tod == "night" else "#7A6A8A", "matte")
            pm = geo.PartMesh(f"{name}_tower")
            pm.add(bm_rounded_box((0.7, 0.4, 3.6), 0.02, 1, (0, 0, 1.8)), "x", tm)
            pm.add(geo.bm_cone(0.55, 0.0, 0.9, center=(0, 0, 4.05), segments=4, rot=euler(z=45)), "x", tm)
            face = self.mats.surface("tower_face", "#FFF4D6", "plastic", emission=2.0 if self.tod == "night" else 0.8)
            pm.add(bm_cylinder(0.22, 0.05, center=(0, -0.21, 3.0), rot=euler(x=90)), "x", face)
            pm.add(bm_rounded_box((4.0, 0.3, 0.9), 0.02, 1, (1.4, 0.2, 0.45)), "x", tm)
            to = pm.build(self.coll)
            to.location = (x + w * 0.15, y + 1.1, z - h * 0.55)
            to.rotation_euler = (0, 0, math.radians(rot_z))
        return o

    def arched_window(self, name: str, x: float, y: float, z0: float, w: float, h: float, frame_mat, rot_z=0.0):
        pm = geo.PartMesh(name)
        t = 0.06
        for sx in (-1, 1):
            pm.add(bm_rounded_box((t, t * 1.6, h), 0.01, 1, (sx * w / 2, 0, h / 2)), "x", frame_mat)
        pm.add(bm_rounded_box((w + t, t * 1.6, t), 0.01, 1, (0, 0, 0)), "x", frame_mat)
        pm.add(bm_rounded_box((t * 0.6, t, h), 0.005, 1, (0, 0, h / 2)), "x", frame_mat)
        for k in range(1, 3):
            pm.add(bm_rounded_box((w, t, t * 0.6), 0.005, 1, (0, 0, h * k / 3)), "x", frame_mat)
        arch = geo.bm_torus(w / 2, t * 0.6, center=(0, 0, h), rot=euler(x=90), seg_major=32, seg_minor=6)
        bmesh.ops.delete(arch, geom=[v for v in arch.verts if v.co.z < h - 0.01], context="VERTS")
        pm.add(arch, "x", frame_mat)
        sill = bm_rounded_box((w + 0.25, 0.25, 0.06), 0.01, 1, (0, -0.1, -0.02))
        pm.add(sill, "x", frame_mat)
        o = pm.build(self.coll)
        o.location = (x, y, z0)
        o.rotation_euler = (0, 0, math.radians(rot_z))
        self.objects[name] = o
        return o

    def table(self, name: str, x, y, w, d, h, mat):
        pm = geo.PartMesh(name)
        pm.add(bm_rounded_box((w, d, 0.05), 0.015, 2, (0, 0, h - 0.025)), "x", mat)
        for sx in (-1, 1):
            for sy in (-1, 1):
                pm.add(bm_rounded_box((0.06, 0.06, h - 0.05), 0.01, 1, (sx * (w / 2 - 0.08), sy * (d / 2 - 0.08), (h - 0.05) / 2)),
                       "x", mat)
        o = pm.build(self.coll)
        o.location = (x, y, 0)
        self.objects[name] = o
        return o

    def lamp(self, name: str, x, y, z, color="#2F6B4F"):
        pm = geo.PartMesh(name)
        brass = self.mats.surface("brass", "#C8A04A", "brass")
        shade = self.mats.surface(f"{name}_shade", color, "plastic")
        pm.add(bm_cylinder(0.07, 0.02, center=(0, 0, 0.01)), "x", brass)
        pm.add(bm_cylinder(0.008, 0.2, center=(0, 0, 0.11)), "x", brass)
        sh = bm_cylinder(0.11, 0.07, center=(0, 0, 0.23), radius2=0.05)
        pm.add(sh, "x", shade)
        bulb = self.mats.surface("bulb", "#FFE6A8", "plastic", emission=6.0)
        pm.add(bm_sphere(0.03, center=(0, 0, 0.19), u=10, v=6), "x", bulb)
        o = pm.build(self.coll)
        o.location = (x, y, z)
        light = bpy.data.lights.new(f"{name}_light", "POINT")
        light.energy = 18.0
        light.color = (1.0, 0.82, 0.55)
        light.shadow_soft_size = 0.05
        lo = bpy.data.objects.new(f"{name}_light", light)
        self.coll.objects.link(lo)
        lo.location = (x, y, z + 0.17)
        self.objects[name] = o
        return o

    def gear(self, name: str, radius: float, teeth: int, thickness: float, mat, location, rot_axis="Y"):
        bm = bmesh.new()
        ring = []
        for i in range(teeth * 4):
            a = 2 * math.pi * i / (teeth * 4)
            r = radius * (1.0 if (i % 4) in (1, 2) else 0.86)
            ring.append((math.cos(a) * r, math.sin(a) * r))
        top = [bm.verts.new((x, y, thickness / 2)) for x, y in ring]
        bot = [bm.verts.new((x, y, -thickness / 2)) for x, y in ring]
        bm.faces.new(top)
        bm.faces.new(list(reversed(bot)))
        n = len(ring)
        for i in range(n):
            bm.faces.new((bot[i], bot[(i + 1) % n], top[(i + 1) % n], top[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        # spokes cut-outs are expensive; add a hub + rim ring instead
        hub = bm_cylinder(radius * 0.18, thickness * 1.6, segments=24)
        tmp = bpy.data.meshes.new("_hub")
        hub.to_mesh(tmp)
        hub.free()
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        for k in range(5):
            a = 2 * math.pi * k / 5
            sp = bm_rounded_box((radius * 0.75, radius * 0.1, thickness * 1.15), 0.005, 1,
                                center=(math.cos(a) * radius * 0.4, math.sin(a) * radius * 0.4, 0), rot=euler(z=math.degrees(a)))
            tmp = bpy.data.meshes.new("_sp")
            sp.to_mesh(tmp)
            sp.free()
            bm.from_mesh(tmp)
            bpy.data.meshes.remove(tmp)
        bevel_edges = [e for e in bm.edges if e.calc_face_angle(0) > 0.6]
        if bevel_edges:
            bmesh.ops.bevel(bm, geom=bevel_edges, offset=min(0.01, thickness * 0.2), segments=1, affect="EDGES",
                            clamp_overlap=True)
        o = self.obj(name, bm, mat, smooth=False)
        o.location = location
        if rot_axis == "Y":
            o.rotation_euler = (math.radians(90), 0, 0)
        elif rot_axis == "X":
            o.rotation_euler = (0, math.radians(90), 0)
        self.anim_targets.setdefault("gears", []).append(o)
        o["sf_gear_speed"] = (1 if len(self.anim_targets["gears"]) % 2 else -1) * 0.6 / max(radius, 0.2)
        return o

    # ------------------------------------------------------------------ presets
    def build(self):
        getattr(self, f"build_{self.preset}", self.build_library)()
        return self

    def build_library(self):
        pal = self.pal
        self.floor(self.wood("floor_planks", pal["floor"], scale=1.2))
        wall = self.mats.surface("lib_wall", pal["wall"], "matte")
        wains = self.wood("wainscot", pal["trim"], planks=False)
        h = self.loc["wall_height"]
        self.wall("wall_back", -4.2, 3.0, 4.2, 3.0, h, wall)
        self.wall("wall_left", -4.0, -3.5, -4.0, 3.0, h, wall)
        self.wall("wall_right", 4.0, -3.5, 4.0, 3.0, h, wall)
        self.wall("wainscot_back", -4.2, 2.93, 4.2, 2.93, 0.9, wains, thickness=0.04)
        ceiling = bm_rounded_box((9, 7, 0.1), 0, 0, (0, 0, h + 0.05))
        self.obj("ceiling", ceiling, self.mats.surface("ceiling", "#5B4A3A", "matte"), smooth=False)
        for i, x in enumerate((-3.1, -1.9, 1.9)):
            self.books_shelf(f"shelf_{i}", x, 2.72, 1.15, 2.6, 0.38)
        for i, y in enumerate((-0.6, 0.8, 2.0)):
            self.books_shelf(f"shelf_l{i}", -3.75, y, 1.1, 2.4, 0.38, rot_z=90)
        # arched window on the back wall (right of centre) with the clock tower outside
        frame = self.wood("window_frame", "#F2E6CF", planks=False)
        self.arched_window("window", 0.35, 2.95, 1.0, 1.25, 1.55, frame)
        sky = ("#F7C59F", "#9FD3E6") if self.tod in ("afternoon", "sunset", "evening") else ("#BFE3F2", "#6FB7E0")
        if self.tod == "night":
            sky = ("#1B2347", "#0B0F24")
        self.window_view("window_view", 0.35, 2.95, 1.9, 1.3, 1.6, sky[1], sky[0], 2.2 if self.tod != "night" else 0.6,
                         stars=self.tod == "night")
        rug_mat = self.mats.surface("rug", "#7B2D3A", "cloth", "stripes", "#C9A227")
        rug = bm_cylinder(1.25, 0.012, center=(0, 0.45, 0.006), segments=48)
        self.obj("rug", rug, rug_mat)
        table_mat = self.wood("table_wood", "#7A4A2A", planks=False)
        self.table("reading_table", 0.0, 0.52, 1.1, 0.62, 0.5, table_mat)
        self.lamp("table_lamp", -0.38, 0.62, 0.5, pal["accent"])
        for i, (x, y, rz) in enumerate(((-0.95, 1.0, 20), (0.95, 1.0, -20))):
            pm = geo.PartMesh(f"chair_{i}")
            cm = self.wood("chair_wood", "#6B4226", planks=False)
            pm.add(bm_rounded_box((0.36, 0.36, 0.04), 0.01, 1, (0, 0, 0.3)), "x", cm)
            pm.add(bm_rounded_box((0.36, 0.04, 0.4), 0.01, 1, (0, 0.17, 0.5)), "x", cm)
            for sx in (-1, 1):
                for sy in (-1, 1):
                    pm.add(bm_rounded_box((0.035, 0.035, 0.3), 0.005, 1, (sx * 0.15, sy * 0.15, 0.15)), "x", cm)
            o = pm.build(self.coll)
            o.location = (x, y + 0.6, 0)
            o.rotation_euler = (0, 0, math.radians(rz))
        # book stack + globe props on the table edge for depth
        bm = bm_rounded_box((0.22, 0.16, 0.05), 0.005, 1, (0.4, 0.62, 0.525))
        self.obj("book_stack_1", bm, self.mats.surface("book_red", "#8E3B46", "cloth"))
        bm = bm_rounded_box((0.2, 0.15, 0.04), 0.005, 1, (0.41, 0.6, 0.57), rot=euler(z=12))
        self.obj("book_stack_2", bm, self.mats.surface("book_blue", "#1F4E79", "cloth"))
        # posters (generic shapes, no text/brands)
        for i, (x, col) in enumerate(((-0.75, "#E8B33C"), (1.25, "#5FA8D3"))):
            pm = geo.PartMesh(f"poster_{i}")
            pm.add(bm_rounded_box((0.5, 0.01, 0.7), 0.0, 0, (0, 0, 0)), "x", self.mats.surface(f"poster{i}", col, "paper"))
            pm.add(bm_cylinder(0.12, 0.012, center=(0, -0.008, 0.08), rot=euler(x=90)), "x",
                   self.mats.surface("poster_dot", "#F7F1E3", "paper"))
            pm.add(bm_rounded_box((0.3, 0.012, 0.05), 0, 0, (0, -0.008, -0.2)), "x",
                   self.mats.surface("poster_bar", "#2B2D42", "paper"))
            o = pm.build(self.coll)
            o.location = (x, 2.93, 1.7)

    def build_clock_tower(self):
        pal = self.pal
        self.floor(self.wood("floor_planks_dark", pal["floor"], scale=1.0))
        h = self.loc["wall_height"]
        stone = self.stone("tower_stone", pal["wall"])
        self.wall("wall_back", -4.6, 3.3, 4.6, 3.3, h, stone, thickness=0.3)
        self.wall("wall_left", -4.4, -3.5, -4.4, 3.3, h, stone, thickness=0.3)
        self.wall("wall_right", 4.4, -3.5, 4.4, 3.3, h, stone, thickness=0.3)
        # giant clock face (seen from inside: translucent glass lit by the moon)
        glass_col = "#C9D8FF" if self.tod == "night" else "#FFF4D6"
        glass = self.mats.surface("clock_glass", glass_col, "plastic", emission=1.6 if self.tod == "night" else 2.5)
        iron = self.mats.surface("iron", "#2B2A30", "metal")
        cz = 2.7
        face = bm_cylinder(1.65, 0.04, center=(0, 3.12, cz), rot=euler(x=90), segments=64)
        self.obj("clock_glass", face, glass)
        rim = geo.bm_torus(1.7, 0.09, center=(0, 3.08, cz), rot=euler(x=90), seg_major=64, seg_minor=8)
        self.obj("clock_rim", rim, iron)
        pm = geo.PartMesh("clock_marks")
        for k in range(12):
            a = 2 * math.pi * k / 12
            ln = 0.32 if k % 3 == 0 else 0.18
            mark = bm_rounded_box((0.07 if k % 3 == 0 else 0.045, 0.04, ln), 0.01, 1,
                                  center=(math.sin(a) * 1.35, 3.06, cz + math.cos(a) * 1.35), rot=euler(y=-math.degrees(a)))
            pm.add(mark, "x", iron)
        for k in range(8):  # window mullions
            a = 2 * math.pi * k / 8
            pm.add(bm_rounded_box((0.035, 0.03, 1.6), 0.005, 1, center=(math.sin(a) * 0.8, 3.08, cz + math.cos(a) * 0.8),
                                  rot=euler(y=-math.degrees(a))), "x", iron)
        self.objects["clock_marks"] = pm.build(self.coll)
        hand_h = bm_rounded_box((0.09, 0.03, 1.0), 0.01, 1, center=(0, 0, 0.42))
        hh = self.obj("clock_hand_hour", hand_h, iron)
        hh.location = (0, 3.0, cz)
        hh.rotation_euler = (0, math.radians(-110), 0)
        hand_m = bm_rounded_box((0.06, 0.03, 1.35), 0.01, 1, center=(0, 0, 0.6))
        hm = self.obj("clock_hand_minute", hand_m, iron)
        hm.location = (0, 2.98, cz)
        hm.rotation_euler = (0, math.radians(15), 0)
        self.anim_targets["clock_hands"] = [hh, hm]
        hub = bm_cylinder(0.12, 0.12, center=(0, 2.95, cz), rot=euler(x=90))
        self.obj("clock_hub", hub, self.mats.surface("brass", "#C8A04A", "brass"))
        # sky behind the clock
        self.window_view("clock_sky", 0, 3.3, cz - 1.0, 2.0, 2.0, "#0B0F24" if self.tod == "night" else "#9FD3E6",
                         "#1B2347" if self.tod == "night" else "#F7C59F", 1.0, tower=False, stars=self.tod == "night")
        # gears
        brass = self.mats.surface("gear_brass", "#B8862F", "brass")
        bronze = self.mats.surface("gear_bronze", "#8C5A2B", "brass")
        for name, r, t, loc, m in (("gear_big_l", 1.15, 22, (-2.5, 2.4, 2.4), brass),
                                    ("gear_mid_l", 0.62, 14, (-1.55, 2.2, 1.35), bronze),
                                    ("gear_big_r", 1.3, 26, (2.6, 2.5, 3.0), bronze),
                                    ("gear_small_r", 0.45, 11, (1.75, 2.1, 1.25), brass),
                                    ("gear_top", 0.8, 18, (-0.9, 2.6, 4.6), brass),
                                    ("gear_front_l", 0.5, 12, (-3.4, -0.6, 0.9), bronze)):
            self.gear(name, r, t, 0.08, m, loc, "Y")
        beam_mat = self.wood("beam_wood", pal["trim"], planks=False)
        for x in (-3.6, 3.6):
            self.obj(f"post_{x}", bm_rounded_box((0.22, 0.22, h), 0.02, 1, (x, 2.6, h / 2)), beam_mat)
        self.obj("beam_top", bm_rounded_box((8.4, 0.24, 0.24), 0.02, 1, (0, 2.6, 4.0)), beam_mat)
        self.obj("beam_diag", bm_rounded_box((0.18, 0.18, 3.4), 0.02, 1, (-3.0, 2.55, 2.2), rot=euler(y=35)), beam_mat)
        # stairs on the left
        pm = geo.PartMesh("stairs")
        for k in range(9):
            pm.add(bm_rounded_box((0.9, 0.34, 0.06), 0.01, 1, (-3.5, -1.2 + k * 0.32, 0.18 + k * 0.22)), "x", beam_mat)
        pm.add(bm_rounded_box((0.08, 3.4, 0.08), 0.01, 1, (-3.05, 0.1, 1.6), rot=euler(x=-34)), "x", beam_mat)
        self.objects["stairs"] = pm.build(self.coll)
        # the hidden gap under the clock face where the twelfth gear hides
        hidden = self.mats.surface("gear_hidden", "#D4A73A", "brass")
        g = self.gear("gear_twelfth", 0.28, 9, 0.05, hidden, (0.62, 2.95, 0.42), "Y")
        g["sf_hidden_gear"] = True
        crate_mat = self.wood("crate", "#6E4A2E", planks=False)
        for i, (x, y, s) in enumerate(((2.9, 0.6, 0.45), (3.2, 1.1, 0.35), (2.6, 1.3, 0.3))):
            self.obj(f"crate_{i}", bm_rounded_box((s, s, s), 0.02, 1, (x, y, s / 2)), crate_mat)

    def build_hallway(self):
        pal = self.pal
        tile = self.mats.surface("tile", pal["floor"], "plastic", "plaid", "#B3ADA3")
        self.floor(tile)
        wall = self.mats.surface("hall_wall", pal["wall"], "matte")
        h = self.loc["wall_height"]
        self.wall("wall_back", -7, 2.4, 7, 2.4, h, wall)
        locker = self.mats.surface("locker", pal["trim"], "metal")
        pm = geo.PartMesh("lockers")
        for k in range(16):
            x = -5.6 + k * 0.7
            pm.add(bm_rounded_box((0.66, 0.4, 1.9), 0.02, 1, (x, 2.15, 0.95)), "x", locker)
            pm.add(bm_rounded_box((0.06, 0.02, 0.12), 0.005, 1, (x + 0.22, 1.94, 1.0)), "x",
                   self.mats.surface("handle", "#CCCCCC", "metal"))
        self.objects["lockers"] = pm.build(self.coll)
        light = self.mats.surface("ceiling_light", "#FFFFFF", "plastic", emission=4.0)
        for k in range(4):
            self.obj(f"cl_{k}", bm_rounded_box((1.2, 0.3, 0.04), 0.01, 1, (-4.5 + k * 3, 0.6, h - 0.05)), light)
        self.obj("ceiling", bm_rounded_box((14, 5, 0.1), 0, 0, (0, 0, h + 0.05)), self.mats.surface("hall_ceil", "#EDEDED", "matte"))

    def build_street(self):
        pal = self.pal
        self.floor(self.stone("cobbles", pal["floor"]))
        colors = ["#E7C9A9", "#BFD8C8", "#E8B4A0", "#C9C3E6", "#F2D7A0"]
        for k in range(6):
            x = -7 + k * 2.8
            hgt = self.rng.uniform(3.0, 4.6)
            pm = geo.PartMesh(f"shop_{k}")
            pm.add(bm_rounded_box((2.6, 1.6, hgt), 0.03, 1, (0, 0, hgt / 2)), "x", self.mats.surface(f"shop{k}", colors[k % 5], "matte"))
            pm.add(bm_rounded_box((1.6, 0.05, 1.1), 0.01, 1, (0, -0.81, 1.0)), "x",
                   self.mats.surface("shop_window", "#FFE9B0", "plastic", emission=0.6))
            pm.add(bm_rounded_box((2.7, 0.7, 0.08), 0.02, 1, (0, -1.05, 1.9), rot=euler(x=-15)), "x",
                   self.mats.surface(f"awning{k}", self.rng.choice(["#D64541", "#2E8B57", "#3D6B8C"]), "cloth", "stripes", "#F7F1E3"))
            o = pm.build(self.coll)
            o.location = (x, 5.2, 0)
        self.window_view("sky", 0, 9.0, 0.0, 14, 6, "#6FB7E0" if self.tod != "night" else "#0B0F24",
                         "#CFEAF5" if self.tod != "night" else "#1B2347", 1.0, tower=True, stars=self.tod == "night")


def animate_set(builder: SetBuilder, events: list[dict], fps: int, frame_start: int, frame_end: int):
    """Event-driven set animation (e.g. the clock tower gears start turning on `gears_start`)."""
    from storyforge_blender import compat

    start_t = None
    for ev in events:
        if ev.get("type") == "sfx" and ev.get("tag") in ("gears_start", "clock_start"):
            start_t = ev["t"]
            break
    if start_t is None:
        return
    f0 = frame_start + int(round(start_t * fps))
    for g in builder.anim_targets.get("gears", []):
        speed = float(g.get("sf_gear_speed", 0.5))  # radians per second
        base = g.rotation_euler[2]
        keys = [(f0, base), (f0 + int(fps * 0.8), base + speed * 0.25),
                (frame_end, base + speed * 0.25 + speed * (frame_end - f0 - fps * 0.8) / fps)]
        compat.set_keys(g, "rotation_euler", 2, keys, "BEZIER")
    for i, hnd in enumerate(builder.anim_targets.get("clock_hands", [])):
        base = hnd.rotation_euler[1]
        compat.set_keys(hnd, "rotation_euler", 1, [(f0, base), (f0 + int(fps * 0.4), base + math.radians(6 if i else 0.5)),
                                                   (frame_end, base + math.radians(6 if i else 0.5) +
                                                    math.radians(0.5 if i else 0.05) * (frame_end - f0) / fps)], "LINEAR")
