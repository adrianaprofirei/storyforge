"""Materials for both style presets.

stylized_3d: physically based "toy plastic / fabric" Principled BSDF materials (EEVEE + Cycles).
cartoon:     cel shading — Diffuse -> Shader to RGB -> constant ColorRamp bands with a hue-shifted
             shadow colour, a thin rim band, emitted flat (EEVEE). Outlines come from Line Art.

Faces are shader-driven so they animate with plain keyframes in any engine:
* eyes: pupil position, pupil size, upper/lower lid lines, lid tilt and a lash line are computed
  from object-space coordinates and the eye object's custom properties (gaze_x, gaze_y, lid_top,
  lid_bottom, lid_tilt, pupil_scale). Lids take the skin colour, so a closing lid is a real lid.
* mouth: interior/teeth/tongue from UVs (v=0 lower lip, v=1 upper lip) on a shape-keyed mesh.
* FX/decals: opacity from the object colour alpha (keyable `obj.color[3]`).
"""

from __future__ import annotations

import bpy

from storyforge_blender.geo import Nodes, hex_rgba, mix_rgba, scale_rgba

SHADOW_TINT = (0.36, 0.38, 0.62, 1.0)


class MaterialFactory:
    def __init__(self, style: str = "stylized_3d"):
        self.style = style
        self.cache: dict = {}

    @property
    def toon(self) -> bool:
        return self.style == "cartoon"

    def _key(self, *k):
        return (self.style,) + k

    # ------------------------------------------------------------------ generic surfaces
    def surface(self, name: str, color, kind: str = "plastic", pattern: str = "solid", pattern_color=None,
                emission: float = 0.0):
        if isinstance(color, str):
            color = hex_rgba(color)
        if isinstance(pattern_color, str):
            pattern_color = hex_rgba(pattern_color)
        key = self._key(name, tuple(round(c, 4) for c in color), kind, pattern,
                        tuple(round(c, 4) for c in pattern_color) if pattern_color else None, emission)
        if key in self.cache:
            return self.cache[key]
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = color
        n = Nodes(mat)
        base = self._pattern(n, color, pattern, pattern_color)
        if emission > 0:
            em = n.node("ShaderNodeEmission")
            n._in(em, "Color", base)
            em.inputs["Strength"].default_value = emission
            n.output(em.outputs[0])
        elif self.toon:
            n.output(self._toon(n, base, kind))
        else:
            n.output(self._pbr(n, base, kind))
        self.cache[key] = mat
        return mat

    def _pattern(self, n: Nodes, color, pattern: str, pcolor):
        if pattern in (None, "solid", "emblem") or pcolor is None:
            return color
        co = n.texcoord("Object")
        x, y, z = n.separate(co)
        if pattern == "stripes":
            s = n.math("SINE", n.math("MULTIPLY", z, 62.0))
            m = n.smooth_step(-0.08, 0.08, s)
        elif pattern == "plaid":
            a = n.smooth_step(-0.1, 0.1, n.math("SINE", n.math("MULTIPLY", z, 48.0)))
            b = n.smooth_step(-0.1, 0.1, n.math("SINE", n.math("MULTIPLY", x, 48.0)))
            m = n.math("MULTIPLY", n.math("ADD", a, b), 0.5)
        elif pattern == "dots":
            vor = n.node("ShaderNodeTexVoronoi")
            vor.inputs["Scale"].default_value = 38.0
            n.link(co, vor.inputs["Vector"])
            m = n.smooth_step(0.24, 0.2, vor.outputs["Distance"])
        elif pattern == "gradient":
            m = n.map_range(z, 0.45, 0.85, 0.0, 1.0)
        else:
            return color
        return n.mix_color(m, color, pcolor)

    def _pbr(self, n: Nodes, base, kind: str):
        presets = {
            "plastic": dict(roughness=0.38, Coat_Weight=0.25, Coat_Roughness=0.2, Specular_IOR_Level=0.5),
            "skin": dict(roughness=0.48, Subsurface_Weight=0.12, Subsurface_Scale=0.02, Coat_Weight=0.08,
                         Specular_IOR_Level=0.45),
            "cloth": dict(roughness=0.82, Sheen_Weight=0.35, Sheen_Roughness=0.5, Specular_IOR_Level=0.35),
            "hair": dict(roughness=0.32, Coat_Weight=0.3, Coat_Roughness=0.25, Specular_IOR_Level=0.55),
            "rubber": dict(roughness=0.62, Specular_IOR_Level=0.4),
            "metal": dict(roughness=0.32, Metallic=1.0),
            "brass": dict(roughness=0.28, Metallic=1.0),
            "wood": dict(roughness=0.6, Specular_IOR_Level=0.4, Coat_Weight=0.1),
            "paper": dict(roughness=0.9, Specular_IOR_Level=0.25),
            "glass": dict(roughness=0.05, Transmission_Weight=0.9, IOR=1.45),
            "matte": dict(roughness=0.9, Specular_IOR_Level=0.3),
        }
        p = presets.get(kind, presets["plastic"])
        rough = p.pop("roughness", 0.5)
        return n.principled(base, rough, **p)

    def _toon(self, n: Nodes, base, kind: str):
        diff = n.node("ShaderNodeBsdfDiffuse")
        diff.inputs["Color"].default_value = (1, 1, 1, 1)
        s2r = n.node("ShaderNodeShaderToRGB")
        n.link(diff.outputs[0], s2r.inputs[0])
        bw = n.node("ShaderNodeRGBToBW")
        n.link(s2r.outputs["Color"], bw.inputs[0])
        ramp = n.node("ShaderNodeValToRGB")
        cr = ramp.color_ramp
        cr.interpolation = "CONSTANT"
        cr.elements[0].position = 0.0
        cr.elements[0].color = (0.0, 0.0, 0.0, 1)
        cr.elements[1].position = 0.08
        cr.elements[1].color = (0.62, 0.62, 0.62, 1)
        e = cr.elements.new(0.38)
        e.color = (1.0, 1.0, 1.0, 1)
        n.link(bw.outputs[0], ramp.inputs["Fac"])
        lit = n.math("MAXIMUM", ramp.outputs["Color"], 0.0)
        # shadow colour: base * tint (hue shifted toward blue/purple), lit = base
        shadow = n.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", clamp_factor=True)
        shadow.inputs["Factor"].default_value = 1.0
        n._in(shadow, 6, base)
        shadow.inputs[7].default_value = SHADOW_TINT
        col = n.mix_color(n.smooth_step(0.3, 0.7, lit), shadow.outputs[2], base)
        darkest = n.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", clamp_factor=True)
        darkest.inputs["Factor"].default_value = 1.0
        n._in(darkest, 6, shadow.outputs[2])
        darkest.inputs[7].default_value = (0.7, 0.7, 0.8, 1)
        col = n.mix_color(n.smooth_step(0.0, 0.3, lit), darkest.outputs[2], col)
        # rim band
        lw = n.node("ShaderNodeLayerWeight")
        lw.inputs["Blend"].default_value = 0.35
        rim = n.smooth_step(0.72, 0.75, lw.outputs["Facing"])
        rim = n.math("MULTIPLY", rim, n.smooth_step(0.5, 0.9, lit))
        col = n.mix_color(n.math("MULTIPLY", rim, 0.35), col, (1, 1, 1, 1))
        em = n.node("ShaderNodeEmission")
        n._in(em, "Color", col)
        em.inputs["Strength"].default_value = 1.0
        return em.outputs[0]

    # ------------------------------------------------------------------ faces
    def eyes(self, name: str, skin_hex: str, iris_hex: str, eye_cx: float, eye_cz: float, rx: float, rz: float):
        """Eye material for an object whose origin is the head centre and whose two eyes sit at
        x=+-eye_cx, z=eye_cz with radii rx (horizontal) and rz (vertical)."""
        mat = bpy.data.materials.new(name)
        n = Nodes(mat)
        co = n.texcoord("Object")
        x, _y, z = n.separate(co)
        sgn = n.math("SIGN", x)
        lx = n.math("SUBTRACT", x, n.math("MULTIPLY", sgn, eye_cx))  # per-eye local x (signed)
        lz = n.math("SUBTRACT", z, eye_cz)
        u_out = n.math("MULTIPLY", lx, sgn)  # + toward the outer corner for both eyes
        gx = n.attr("gaze_x")
        gy = n.attr("gaze_y")
        ps = n.math("MAXIMUM", n.attr("pupil_scale"), 0.2)
        # pupil
        px = n.math("SUBTRACT", lx, n.math("MULTIPLY", gx, rx * 0.42))
        pz = n.math("SUBTRACT", lz, n.math("MULTIPLY", gy, rz * 0.32))
        pr = n.math("MULTIPLY", ps, rx * 0.56)
        pd = n.math("DIVIDE", n.vmath("LENGTH", n.combine(px, pz, 0.0)), pr)
        pupil = n.smooth_step(1.0, 0.9, pd)
        core = n.smooth_step(0.62, 0.52, pd)
        # catchlights (fixed offset up/outer from the pupil centre)
        hl_x = n.math("SUBTRACT", px, n.math("MULTIPLY", sgn, -rx * 0.15))
        hl_z = n.math("SUBTRACT", pz, rz * 0.18)
        hl = n.smooth_step(rx * 0.12, rx * 0.09, n.vmath("LENGTH", n.combine(hl_x, hl_z, 0.0)))
        hl2 = n.smooth_step(rx * 0.06, rx * 0.04, n.vmath("LENGTH", n.combine(
            n.math("ADD", px, n.math("MULTIPLY", sgn, -rx * 0.12)), n.math("ADD", pz, rz * 0.16), 0.0)))
        iris = hex_rgba(iris_hex)
        white = (0.93, 0.93, 0.9, 1.0)
        col = n.mix_color(pupil, white, iris)
        col = n.mix_color(core, col, scale_rgba(iris, 0.12))
        col = n.mix_color(n.math("MAXIMUM", hl, hl2), col, (1, 1, 1, 1))
        # lids: upper line z_top = rz*(1-2*lid_top) + tilt*0.45*rz*(u/rx); lower line with an upward arc
        lid_top = n.attr("lid_top")
        top_line = n.math("ADD", n.math("MULTIPLY", n.math("SUBTRACT", 1.0, n.math("MULTIPLY", lid_top, 2.0)), rz * 1.04),
                          n.math("MULTIPLY", n.attr("lid_tilt"), n.math("MULTIPLY", u_out, 0.45 * rz / rx)))
        lid_b = n.attr("lid_bottom")
        u2 = n.math("POWER", n.math("DIVIDE", u_out, rx), 2.0)
        bot_line = n.math("SUBTRACT", n.math("MULTIPLY", n.math("SUBTRACT", n.math("MULTIPLY", lid_b, 2.0), 1.0), rz * 1.04),
                          n.math("MULTIPLY", n.math("MULTIPLY", u2, lid_b), 0.35 * rz))
        aa = rz * 0.04
        upper = n.smooth_step(-aa, aa, n.math("SUBTRACT", lz, top_line))
        lower = n.smooth_step(aa, -aa, n.math("SUBTRACT", lz, bot_line))
        lid = n.math("MAXIMUM", upper, lower)
        lash_w = rz * 0.13
        lash = n.math("MULTIPLY", n.smooth_step(-lash_w, -lash_w * 0.6, n.math("SUBTRACT", lz, top_line)),
                      n.math("SUBTRACT", 1.0, upper))
        lash_col = scale_rgba(hex_rgba(skin_hex), 0.18)
        skin = hex_rgba(skin_hex)
        if self.toon:
            eye_col = n.mix_color(lash, col, lash_col)
            final = n.mix_color(lid, eye_col, skin)
            em = n.node("ShaderNodeEmission")
            n._in(em, "Color", final)
            n.output(em.outputs[0])
        else:
            eye_sh = n.principled(n.mix_color(lash, col, lash_col), 0.08, Coat_Weight=0.6, Coat_Roughness=0.05,
                                  Specular_IOR_Level=0.6)
            lid_sh = n.principled(skin, 0.48, Subsurface_Weight=0.1, Subsurface_Scale=0.02)
            n.output(n.mix_shader(lid, eye_sh, lid_sh))
        return mat

    def mouth(self, name: str, lips_hex: str, skin_hex: str):
        mat = bpy.data.materials.new(name)
        n = Nodes(mat)
        uv = n.node("ShaderNodeUVMap")
        u, v, _ = n.separate(uv.outputs[0])
        interior = (0.22, 0.035, 0.04, 1.0)
        teeth = n.smooth_step(0.74, 0.8, v)
        du = n.math("ABSOLUTE", n.math("SUBTRACT", u, 0.5))
        tongue = n.math("MULTIPLY", n.smooth_step(0.34, 0.24, v), n.smooth_step(0.3, 0.2, du))
        col = n.mix_color(teeth, interior, (0.92, 0.9, 0.86, 1.0))
        col = n.mix_color(tongue, col, (0.75, 0.25, 0.3, 1.0))
        if self.toon:
            em = n.node("ShaderNodeEmission")
            n._in(em, "Color", col)
            n.output(em.outputs[0])
        else:
            n.output(n.principled(col, 0.35, Specular_IOR_Level=0.4))
        return mat

    def lips(self, name: str, lips_hex: str):
        return self.surface(name, scale_rgba(hex_rgba(lips_hex), 0.55), "skin")

    def decal(self, name: str, color_hex: str, emission: float = 0.0):
        """Alpha from the object colour (keyable obj.color[3]); used for blush, FX symbols."""
        mat = bpy.data.materials.new(name)
        n = Nodes(mat)
        info = n.node("ShaderNodeObjectInfo")
        alpha = info.outputs["Alpha"]
        col = hex_rgba(color_hex)
        if self.toon or emission > 0:
            em = n.node("ShaderNodeEmission")
            em.inputs["Color"].default_value = col
            em.inputs["Strength"].default_value = max(1.0, emission)
            shader = em.outputs[0]
        else:
            shader = n.principled(col, 0.5)
        tr = n.node("ShaderNodeBsdfTransparent")
        n.output(n.mix_shader(alpha, tr.outputs[0], shader))
        _set_blend(mat)
        return mat


def _set_blend(mat) -> None:
    for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, val)
            except TypeError:
                pass
    if hasattr(mat, "use_transparent_shadow"):
        mat.use_transparent_shadow = True


def lighten(hex_color: str, t: float):
    return mix_rgba(hex_rgba(hex_color), (1, 1, 1, 1), t)
