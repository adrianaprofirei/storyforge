"""bmesh primitives, part assembly and shader-node building helpers."""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector


def hex_rgba(h: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """sRGB hex -> linear RGBA (Blender colour inputs are scene-linear)."""
    h = h.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return (lin[0], lin[1], lin[2], alpha)


def mix_rgba(a, b, t: float):
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(4))


def scale_rgba(a, s: float):
    return (a[0] * s, a[1] * s, a[2] * s, a[3])


# ------------------------------------------------------------------ bmesh primitives
def bm_rounded_box(size, radius: float = 0.02, segments: int = 3, center=(0, 0, 0), rot=None) -> bmesh.types.BMesh:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    r = min(radius, min(size) * 0.49)
    if r > 1e-5 and segments > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=r, offset_type="OFFSET", segments=segments, profile=0.5,
                        affect="EDGES", clamp_overlap=True)
    m = Matrix.Translation(Vector(center))
    if rot is not None:
        m = m @ rot.to_4x4()
    bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
    return bm


def bm_tapered_box(bottom_size, top_size, height: float, radius: float, segments: int = 3, center=(0, 0, 0)):
    bm = bm_rounded_box((1.0, 1.0, height), radius=0.0, segments=0)
    for v in bm.verts:
        t = 1.0 if v.co.z > 0 else 0.0
        sx = bottom_size[0] * (1 - t) + top_size[0] * t
        sy = bottom_size[1] * (1 - t) + top_size[1] * t
        v.co.x *= sx
        v.co.y *= sy
    r = min(radius, min(min(bottom_size), min(top_size), height) * 0.45)
    if r > 1e-5:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=r, offset_type="OFFSET", segments=segments, profile=0.5,
                        affect="EDGES", clamp_overlap=True)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return bm


def bm_sphere(radius: float, scale=(1, 1, 1), center=(0, 0, 0), u: int = 24, v: int = 12):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=radius, calc_uvs=True)
    for vert in bm.verts:
        vert.co = Vector((vert.co.x * scale[0], vert.co.y * scale[1], vert.co.z * scale[2])) + Vector(center)
    return bm


def bm_cylinder(radius: float, depth: float, center=(0, 0, 0), segments: int = 24, rot=None, radius2=None,
                bevel: float = 0.0):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments, radius1=radius,
                          radius2=radius if radius2 is None else radius2, depth=depth)
    if bevel > 0:
        rim = [e for e in bm.edges if len(e.link_faces) == 2 and
               abs(e.link_faces[0].normal.dot(e.link_faces[1].normal)) < 0.5]
        bmesh.ops.bevel(bm, geom=rim, offset=bevel, offset_type="OFFSET", segments=2, profile=0.5, affect="EDGES",
                        clamp_overlap=True)
    m = Matrix.Translation(Vector(center))
    if rot is not None:
        m = m @ rot.to_4x4()
    bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
    return bm


def bm_torus(major: float, minor: float, center=(0, 0, 0), rot=None, seg_major: int = 32, seg_minor: int = 10):
    bm = bmesh.new()
    verts = []
    for i in range(seg_major):
        a = 2 * math.pi * i / seg_major
        ring = []
        for j in range(seg_minor):
            b = 2 * math.pi * j / seg_minor
            x = (major + minor * math.cos(b)) * math.cos(a)
            y = (major + minor * math.cos(b)) * math.sin(a)
            z = minor * math.sin(b)
            ring.append(bm.verts.new((x, y, z)))
        verts.append(ring)
    for i in range(seg_major):
        for j in range(seg_minor):
            a = verts[i][j]
            b = verts[(i + 1) % seg_major][j]
            c = verts[(i + 1) % seg_major][(j + 1) % seg_minor]
            d = verts[i][(j + 1) % seg_minor]
            bm.faces.new((a, b, c, d))
    m = Matrix.Translation(Vector(center))
    if rot is not None:
        m = m @ rot.to_4x4()
    bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
    return bm


def bm_cone(r1: float, r2: float, depth: float, center=(0, 0, 0), rot=None, segments: int = 4):
    return bm_cylinder(r1, depth, center, segments, rot, radius2=r2)


def euler(x=0.0, y=0.0, z=0.0) -> Matrix:
    from mathutils import Euler

    return Euler((math.radians(x), math.radians(y), math.radians(z))).to_matrix()


# ------------------------------------------------------------------ part assembly
class PartMesh:
    """Accumulates many bmesh parts into one mesh with per-part vertex groups + material slots."""

    def __init__(self, name: str):
        self.name = name
        self.bm = bmesh.new()
        self.deform = self.bm.verts.layers.deform.verify()
        self.uv = self.bm.loops.layers.uv.verify()
        self.groups: list[str] = []
        self.materials: list = []

    def group_index(self, group: str) -> int:
        if group not in self.groups:
            self.groups.append(group)
        return self.groups.index(group)

    def mat_index(self, mat) -> int:
        if mat not in self.materials:
            self.materials.append(mat)
        return self.materials.index(mat)

    def add(self, part: bmesh.types.BMesh, group: str, mat, weights: dict[str, float] | None = None) -> None:
        gi = self.group_index(group)
        mi = self.mat_index(mat)
        extra = {self.group_index(g): w for g, w in (weights or {}).items()}
        src_uv = part.loops.layers.uv.active
        vmap = {}
        for v in part.verts:
            nv = self.bm.verts.new(v.co)
            if extra:
                for g, w in extra.items():
                    nv[self.deform][g] = w
                nv[self.deform][gi] = 1.0 - sum(extra.values())
            else:
                nv[self.deform][gi] = 1.0
            vmap[v] = nv
        for f in part.faces:
            try:
                nf = self.bm.faces.new([vmap[v] for v in f.verts])
            except ValueError:
                continue
            nf.material_index = mi
            nf.smooth = True
            if src_uv is not None:
                for lo_src, lo_dst in zip(f.loops, nf.loops, strict=False):
                    lo_dst[self.uv].uv = lo_src[src_uv].uv
        part.free()

    def build(self, collection, sharp_angle: float = 38.0):
        me = bpy.data.meshes.new(self.name)
        self.bm.normal_update()
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.materials:
            me.materials.append(m)
        obj = bpy.data.objects.new(self.name, me)
        collection.objects.link(obj)
        for g in self.groups:
            obj.vertex_groups.new(name=g)
        shade_smooth(me, sharp_angle)
        return obj


def shade_smooth(me, sharp_angle: float = 38.0) -> None:
    for p in me.polygons:
        p.use_smooth = True
    if hasattr(me, "set_sharp_from_angle"):
        me.set_sharp_from_angle(angle=math.radians(sharp_angle))
    elif hasattr(me, "use_auto_smooth"):
        me.use_auto_smooth = True
        me.auto_smooth_angle = math.radians(sharp_angle)


def mesh_object(name: str, bm: bmesh.types.BMesh, collection, mats=(), smooth: bool = True, sharp_angle: float = 38.0):
    me = bpy.data.meshes.new(name)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    if smooth:
        shade_smooth(me, sharp_angle)
    return obj


def merge_bms(*parts) -> bmesh.types.BMesh:
    out = bmesh.new()
    for p in parts:
        me = bpy.data.meshes.new("_tmp")
        p.to_mesh(me)
        p.free()
        out.from_mesh(me)
        bpy.data.meshes.remove(me)
    return out


# ------------------------------------------------------------------ shader node builder
class Nodes:
    """Tiny DSL to build shader graphs readably: values are sockets or floats."""

    def __init__(self, mat):
        mat.use_nodes = True
        self.mat = mat
        self.tree = mat.node_tree
        self.nodes = self.tree.nodes
        self.links = self.tree.links
        self.nodes.clear()
        self.x = 0

    def node(self, kind: str, **props):
        n = self.nodes.new(kind)
        n.location = (self.x, 0)
        self.x += 180
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, src, dst):
        self.links.new(src, dst)

    def _in(self, node, idx, value):
        sock = node.inputs[idx]
        if hasattr(value, "is_output") or hasattr(value, "links"):
            self.link(value, sock)
        else:
            sock.default_value = value

    def math(self, op: str, a, b=0.0, clamp: bool = False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self._in(n, 0, a)
        self._in(n, 1, b)
        return n.outputs[0]

    def vmath(self, op: str, a, b=(0, 0, 0)):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self._in(n, 0, a)
        self._in(n, 1, b)
        return n.outputs["Value"] if op in ("LENGTH", "DOT_PRODUCT", "DISTANCE") else n.outputs[0]

    def attr(self, name: str, kind: str = "OBJECT"):
        n = self.node("ShaderNodeAttribute", attribute_type=kind, attribute_name=name)
        return n.outputs["Fac"]

    def attr_color(self, name: str, kind: str = "OBJECT"):
        n = self.node("ShaderNodeAttribute", attribute_type=kind, attribute_name=name)
        return n.outputs["Color"]

    def texcoord(self, kind: str = "Object"):
        n = self.node("ShaderNodeTexCoord")
        return n.outputs[kind]

    def separate(self, vec):
        n = self.node("ShaderNodeSeparateXYZ")
        self.link(vec, n.inputs[0])
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def combine(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self._in(n, i, v)
        return n.outputs[0]

    def smooth_step(self, edge0: float, edge1: float, x):
        n = self.node("ShaderNodeMapRange", data_type="FLOAT", interpolation_type="SMOOTHSTEP", clamp=True)
        self._in(n, "Value", x)
        n.inputs["From Min"].default_value = edge0
        n.inputs["From Max"].default_value = edge1
        n.inputs["To Min"].default_value = 0.0
        n.inputs["To Max"].default_value = 1.0
        return n.outputs["Result"]

    def map_range(self, x, a, b, c, d, clamp=True):
        n = self.node("ShaderNodeMapRange", data_type="FLOAT", clamp=clamp)
        self._in(n, "Value", x)
        for name, v in (("From Min", a), ("From Max", b), ("To Min", c), ("To Max", d)):
            self._in(n, name, v)
        return n.outputs["Result"]

    def mix_color(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MIX", clamp_factor=True)
        self._in(n, "Factor", fac)
        self._in(n, 6, a)  # A (color)
        self._in(n, 7, b)  # B (color)
        return n.outputs[2]

    def principled(self, color, roughness=0.5, **inputs):
        n = self.node("ShaderNodeBsdfPrincipled")
        self._in(n, "Base Color", color)
        self._in(n, "Roughness", roughness)
        for k, v in inputs.items():
            name = k.replace("_", " ")
            if name in n.inputs:
                self._in(n, name, v)
        return n.outputs[0]

    def mix_shader(self, fac, a, b):
        n = self.node("ShaderNodeMixShader")
        self._in(n, 0, fac)
        self.link(a, n.inputs[1])
        self.link(b, n.inputs[2])
        return n.outputs[0]

    def output(self, shader):
        n = self.node("ShaderNodeOutputMaterial")
        self.link(shader, n.inputs["Surface"])
        return n
