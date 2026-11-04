"""Style presets (stylized 3D / cartoon) and the per-series colour grade (compositor).

The grade is split in two so it is identical across Blender versions and engines:
* compositor (here, saved in the .blend): bloom/glare, exposure, lift/gain tints with warmth,
  contrast and saturation — Blender 4.2 exposes these as node properties, 5.x as input sockets;
  both paths are handled below.
* finishing pass (ffmpeg, storyforge/render/finishing.py): vignette, temporal film grain and the
  optional per-series .cube LUT.
"""

from __future__ import annotations

from storyforge_blender import compat
from storyforge_blender.geo import hex_rgba


def apply_style(scene, spec: dict, characters_coll, set_builder) -> None:
    style = spec["style"]["preset"]
    scene["sf_style"] = style
    if style == "cartoon":
        lines = spec["style"].get("lines", {})
        compat.add_lineart(scene, "SF_LineArt", None, color=(0.05, 0.04, 0.07, 1.0),
                           thickness=int(lines.get("thickness", 3)), camera_based_crease=float(lines.get("crease", 140)))


def _sock(node, name, kind=None):
    for s in node.inputs:
        if s.name == name and (kind is None or s.type == kind):
            return s
    return None


def _set_sock(node, name, value, kind=None) -> bool:
    s = _sock(node, name, kind)
    if s is None or not hasattr(s, "default_value"):
        return False
    try:
        s.default_value = value
        return True
    except (TypeError, ValueError):
        return False


def _set_menu(node, name, candidates) -> None:
    s = _sock(node, name, "MENU")
    if s is None:
        return
    for c in candidates:
        try:
            s.default_value = c
            return
        except (TypeError, ValueError):
            continue


def _image_in(node):
    return next((s for s in node.inputs if s.type == "RGBA"), node.inputs[0])


def apply_grade(scene, grade: dict, style: str) -> None:
    if not grade:
        return
    tree, out_type = compat.compositor_tree(scene)
    if tree is None:
        return
    tree.nodes.clear()
    rl = tree.nodes.new("CompositorNodeRLayers")
    out = tree.nodes.new(out_type)
    cur = rl.outputs["Image"]
    x = 0

    def add(kind):
        nonlocal x
        n = tree.nodes.new(kind)
        n.location = (x, 0)
        x += 220
        return n

    # 1) bloom on bright highlights (lamps, clock face, catchlights)
    glare = add("CompositorNodeGlare")
    compat.set_props(glare, glare_type="BLOOM" if compat.at_least(4, 2) else "FOG_GLOW", quality="MEDIUM",
                     threshold=1.2, mix=-0.75, size=8)
    _set_menu(glare, "Type", ["Bloom", "BLOOM", "Fog Glow"])
    _set_menu(glare, "Quality", ["Medium", "MEDIUM"])
    _set_sock(glare, "Threshold", 1.2)
    _set_sock(glare, "Strength", 0.22)
    _set_sock(glare, "Size", 0.55)
    tree.links.new(cur, _image_in(glare))
    cur = glare.outputs[0]
    # 2) exposure
    ex = add("CompositorNodeExposure")
    _set_sock(ex, "Exposure", float(grade.get("exposure", 0.0)))
    tree.links.new(cur, _image_in(ex))
    cur = ex.outputs[0]
    # 3) lift/gain tints + warmth
    sh = hex_rgba(grade.get("shadows_tint", "#7F7F7F"))
    hi = hex_rgba(grade.get("highlights_tint", "#FFFFFF"))
    warmth = float(grade.get("warmth", 0.0))
    lum_sh = (sh[0] + sh[1] + sh[2]) / 3 or 1.0
    lum_hi = (hi[0] + hi[1] + hi[2]) / 3 or 1.0
    lift = [1.0 + 0.06 * (c / lum_sh - 1.0) for c in sh[:3]]
    gain = [1.0 + 0.08 * (c / lum_hi - 1.0) for c in hi[:3]]
    gain = [gain[0] * (1 + warmth * 0.35), gain[1] * (1 + warmth * 0.05), gain[2] * (1 - warmth * 0.35)]
    cb = add("CompositorNodeColorBalance")
    compat.set_props(cb, correction_method="LIFT_GAMMA_GAIN")
    _set_menu(cb, "Type", ["Lift/Gamma/Gain", "LIFT_GAMMA_GAIN"])
    if not _set_sock(cb, "Lift", (*lift, 1.0), "RGBA"):
        compat.set_props(cb, lift=lift, gain=gain)
    _set_sock(cb, "Gain", (*gain, 1.0), "RGBA")
    tree.links.new(cur, _image_in(cb))
    cur = cb.outputs[0]
    # 4) contrast (Blender's contrast is in percent-ish units: 1.06 -> +6)
    bc = add("CompositorNodeBrightContrast")
    contrast = (float(grade.get("contrast", 1.0)) - 1.0) * 100.0
    if not _set_sock(bc, "Contrast", contrast):
        bc.inputs[2].default_value = contrast
    tree.links.new(cur, _image_in(bc))
    cur = bc.outputs[0]
    # 5) saturation
    hs = add("CompositorNodeHueSat")
    _set_sock(hs, "Saturation", float(grade.get("saturation", 1.0)))
    tree.links.new(cur, _image_in(hs))
    cur = hs.outputs[0]
    tree.links.new(cur, out.inputs[0])
