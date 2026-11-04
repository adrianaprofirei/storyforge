"""Compatibility helpers across Blender 4.2 LTS ... 5.x.

API differences handled here:
* EEVEE engine id: 'BLENDER_EEVEE_NEXT' (4.2-4.5) vs 'BLENDER_EEVEE' (5.x).
* Animation: legacy `Action.fcurves` (<= 4.3) vs slotted actions / channelbags (4.4+, legacy
  API removed in 5.0). We create F-curves through `keyframe_insert` (works everywhere) and then
  look them up in the right container for fast bulk `keyframe_points` editing.
* Compositor: `scene.node_tree` (4.x) vs `scene.compositing_node_group` node groups (5.x).
* Grease Pencil Line Art: GPv2 `grease_pencil_modifiers` (4.2) vs GPv3 regular modifiers (4.3+).
"""

from __future__ import annotations

import bpy

VERSION = bpy.app.version


def at_least(*v) -> bool:
    return tuple(VERSION[: len(v)]) >= tuple(v)


# ------------------------------------------------------------------ engines
def set_engine(scene, kind: str) -> str:
    """kind: 'EEVEE' | 'CYCLES' | 'WORKBENCH'. Returns the engine id actually set."""
    if kind == "CYCLES":
        scene.render.engine = "CYCLES"
        return "CYCLES"
    if kind == "WORKBENCH":
        scene.render.engine = "BLENDER_WORKBENCH"
        return "BLENDER_WORKBENCH"
    for eid in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = eid
            return eid
        except TypeError:
            continue
    raise RuntimeError("EEVEE not available")


def is_eevee(scene) -> bool:
    return scene.render.engine.startswith("BLENDER_EEVEE")


def set_props(obj, **kw) -> None:
    """Set attributes that may not exist in every version (silently skipped)."""
    for k, v in kw.items():
        if hasattr(obj, k):
            try:
                setattr(obj, k, v)
            except (TypeError, AttributeError, ValueError):
                pass


# ------------------------------------------------------------------ animation
def _channelbag(action, slot):
    try:
        from bpy_extras import anim_utils

        fn = getattr(anim_utils, "action_get_channelbag_for_slot", None)
        if fn:
            return fn(action, slot)
    except ImportError:
        pass
    for layer in getattr(action, "layers", []):
        for strip in layer.strips:
            try:
                cb = strip.channelbag(slot)
                if cb:
                    return cb
            except Exception:
                continue
    return None


def find_fcurve(id_data, data_path: str, index: int = 0):
    adt = id_data.animation_data
    if adt is None or adt.action is None:
        return None
    action = adt.action
    slot = getattr(adt, "action_slot", None)
    if slot is not None:
        cb = _channelbag(action, slot)
        if cb is not None:
            return cb.fcurves.find(data_path, index=index)
    fcs = getattr(action, "fcurves", None)
    if fcs is not None:
        return fcs.find(data_path, index=index)
    return None


def all_fcurves(id_data) -> list:
    adt = id_data.animation_data
    if adt is None or adt.action is None:
        return []
    slot = getattr(adt, "action_slot", None)
    if slot is not None:
        cb = _channelbag(adt.action, slot)
        if cb is not None:
            return list(cb.fcurves)
    fcs = getattr(adt.action, "fcurves", None)
    return list(fcs) if fcs is not None else []


def ensure_action(id_data, name: str):
    if id_data.animation_data is None:
        id_data.animation_data_create()
    adt = id_data.animation_data
    if adt.action is None:
        adt.action = bpy.data.actions.new(name)
    return adt.action


def fcurve(id_data, data_path: str, index: int = 0, action_name: str | None = None, group: str | None = None):
    """Get or create an F-curve on the ID's active action, in any Blender version."""
    fc = find_fcurve(id_data, data_path, index)
    if fc is not None:
        return fc
    ensure_action(id_data, action_name or f"{id_data.name}_action")
    # keyframe_insert creates slot/layer/strip/channelbag/fcurve as needed (4.4+), or a legacy fcurve
    kw = {"index": index, "frame": -10000.0}
    if group:
        kw["group"] = group
    try:
        id_data.keyframe_insert(data_path, **kw)
    except TypeError as exc:  # scalar property: index must be -1 (fcurve array_index is 0)
        if "not an array" not in str(exc):
            raise
        kw["index"] = -1
        id_data.keyframe_insert(data_path, **kw)
    fc = find_fcurve(id_data, data_path, index)
    if fc is None:
        raise RuntimeError(f"could not create fcurve {data_path}[{index}] on {id_data.name}")
    # remove the temporary key
    for kp in list(fc.keyframe_points):
        if kp.co[0] == -10000.0:
            fc.keyframe_points.remove(kp)
    return fc


def set_keys(id_data, data_path: str, index: int, keys: list[tuple[float, float]],
             interpolation: str = "BEZIER", group: str | None = None, replace: bool = True,
             handle: str = "AUTO_CLAMPED"):
    """Bulk-insert keyframes [(frame, value), ...] (fast path via foreach_set)."""
    if not keys:
        return None
    fc = fcurve(id_data, data_path, index, group=group)
    if replace:
        fc.keyframe_points.clear()
    keys = sorted(keys, key=lambda k: k[0])
    # dedupe frames (last wins)
    dedup: dict[float, float] = {}
    for f, v in keys:
        dedup[float(f)] = float(v)
    items = sorted(dedup.items())
    start = len(fc.keyframe_points)
    fc.keyframe_points.add(len(items))
    flat = [c for kv in items for c in kv]
    if start == 0:
        fc.keyframe_points.foreach_set("co", flat)
    else:
        for i, (f, v) in enumerate(items):
            fc.keyframe_points[start + i].co = (f, v)
    for kp in fc.keyframe_points:
        kp.interpolation = interpolation
        kp.handle_left_type = handle
        kp.handle_right_type = handle
    fc.update()
    return fc


def set_vector_keys(id_data, data_path: str, keys: list[tuple[float, tuple]], interpolation: str = "BEZIER",
                    group: str | None = None):
    if not keys:
        return
    n = len(keys[0][1])
    for i in range(n):
        set_keys(id_data, data_path, i, [(f, v[i]) for f, v in keys], interpolation, group)


def assign_action(id_data, action) -> None:
    if id_data.animation_data is None:
        id_data.animation_data_create()
    adt = id_data.animation_data
    adt.action = action
    if hasattr(adt, "action_slot") and adt.action_slot is None and hasattr(action, "slots"):
        slots = [s for s in action.slots]
        if slots:
            try:
                adt.action_slot = slots[0]
            except Exception:
                pass


def nla_strip(id_data, track_name: str, action, start: float, name: str | None = None):
    """Add an NLA strip (handles action slots on 4.4+)."""
    if id_data.animation_data is None:
        id_data.animation_data_create()
    adt = id_data.animation_data
    track = adt.nla_tracks.get(track_name) or adt.nla_tracks.new()
    track.name = track_name
    strip = track.strips.new(name or action.name, int(start), action)
    if hasattr(strip, "action_slot") and getattr(strip, "action_slot", None) is None and hasattr(action, "slots"):
        slots = list(action.slots)
        if slots:
            try:
                strip.action_slot = slots[0]
            except Exception:
                pass
    return track, strip


# ------------------------------------------------------------------ compositor
def compositor_tree(scene, create: bool = True):
    """Return (tree, output_node_type) for the compositor in this version."""
    if hasattr(scene, "compositing_node_group"):  # 5.x
        tree = scene.compositing_node_group
        if tree is None and create:
            tree = bpy.data.node_groups.new(f"{scene.name}_compositor", "CompositorNodeTree")
            scene.compositing_node_group = tree
        if tree is not None:
            try:
                if not any(s.in_out == "OUTPUT" for s in tree.interface.items_tree):
                    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
            except Exception:
                pass
        return tree, "NodeGroupOutput"
    scene.use_nodes = True
    return scene.node_tree, "CompositorNodeComposite"


def compositor_input_output(tree, out_type: str):
    rl = next((n for n in tree.nodes if n.bl_idname == "CompositorNodeRLayers"), None)
    if rl is None:
        rl = tree.nodes.new("CompositorNodeRLayers")
    out = next((n for n in tree.nodes if n.bl_idname == out_type), None)
    if out is None:
        out = tree.nodes.new(out_type)
    return rl, out


# ------------------------------------------------------------------ grease pencil line art
def add_lineart(scene, name: str, collection=None, color=(0.05, 0.04, 0.06, 1.0), thickness: int = 3,
                camera_based_crease: float = 140.0):
    """Create a Line Art grease pencil object outlining `collection` (or the whole scene)."""
    mat = bpy.data.materials.new(f"{name}_mat")
    bpy.data.materials.create_gpencil_data(mat)
    mat.grease_pencil.color = color
    if hasattr(bpy.data, "grease_pencils_v3") or at_least(4, 3):
        gp_data_coll = getattr(bpy.data, "grease_pencils_v3", None) or bpy.data.grease_pencils
        gp = gp_data_coll.new(name)
        obj = bpy.data.objects.new(name, gp)
        scene.collection.objects.link(obj)
        layer = gp.layers.new("Lines")
        obj.data.materials.append(mat)
        mod = obj.modifiers.new("LineArt", "LINEART")
        set_props(mod, target_layer=layer.name, target_material=mat)
    else:
        gp = bpy.data.grease_pencils.new(name)
        obj = bpy.data.objects.new(name, gp)
        scene.collection.objects.link(obj)
        layer = gp.layers.new("Lines", set_active=True)
        layer.frames.new(scene.frame_start)
        obj.data.materials.append(mat)
        mod = obj.grease_pencil_modifiers.new("LineArt", "GP_LINEART")
        set_props(mod, target_layer=layer.info, target_material=mat)
    if collection is not None:
        set_props(mod, source_type="COLLECTION", source_collection=collection)
    else:
        set_props(mod, source_type="SCENE")
    set_props(mod, thickness=thickness, radius=thickness * 0.0006, use_crease=True,
              crease_threshold=__import__("math").radians(camera_based_crease), use_intersection=True,
              use_material=True, use_edge_mark=True, use_contour=True, use_loose=False,
              use_overlap_edge_type_support=True, smooth_tolerance=0.1, use_back_face_culling=False)
    return obj, mod
