"""Shot cameras: one camera per shot, keyed motion/lens/focus, bound to timeline markers so the
saved .blend plays as an edited sequence (and any shot can be re-rendered on its own)."""

from __future__ import annotations

import bpy

from storyforge_blender import compat


def build_shot_cameras(scene, shots: list[dict], collection_name: str = "CAMERAS") -> dict:
    coll = bpy.data.collections.new(collection_name)
    scene.collection.children.link(coll)
    scene.timeline_markers.clear()
    cams = {}
    for s in shots:
        cd = bpy.data.cameras.new(f"CAM_{s['id']}")
        cd.sensor_fit = "VERTICAL"
        cd.sensor_height = 36.0
        cd.sensor_width = 36.0
        cd.lens = float(s.get("lens_mm", 40))
        cd.clip_start = 0.02
        cd.clip_end = 200.0
        cd.dof.use_dof = bool(s.get("dof", True))
        cd.dof.aperture_fstop = float(s.get("fstop", 2.8))
        cd.dof.aperture_blades = 7
        cam = bpy.data.objects.new(f"CAM_{s['id']}", cd)
        coll.objects.link(cam)
        cam.rotation_mode = "XYZ"
        keys = s["camera_keys"]
        cam.location = keys[0]["location"]
        cam.rotation_euler = keys[0]["rotation"]
        if len(keys) > 1:
            interp = s.get("interpolation", "BEZIER")
            compat.set_vector_keys(cam, "location", [(k["frame"], k["location"]) for k in keys], interp)
            compat.set_vector_keys(cam, "rotation_euler", [(k["frame"], k["rotation"]) for k in keys], interp)
            if any(abs(k["lens"] - keys[0]["lens"]) > 1e-3 for k in keys):
                compat.set_keys(cd, "lens", 0, [(k["frame"], k["lens"]) for k in keys], interp)
        focus = s.get("focus_keys") or []
        if focus:
            cd.dof.focus_distance = focus[0]["distance"]
            if len(focus) > 1:
                compat.set_keys(cd, "dof.focus_distance", 0, [(k["frame"], k["distance"]) for k in focus], "BEZIER")
        cam["sf_shot"] = s["id"]
        marker = scene.timeline_markers.new(s["id"], frame=int(s["frame_start"]))
        marker.camera = cam
        cams[s["id"]] = cam
    if shots:
        scene.camera = cams[shots[0]["id"]]
    return cams
