"""Render presets, engines, GPU detection and colour management."""

from __future__ import annotations

import bpy

from storyforge_blender import compat

PRESETS = {
    "proxy": {"resolution": (270, 480), "eevee_samples": 8, "cycles_samples": 12, "motion_blur": False,
              "volumetrics": False, "engine": {"stylized_3d": "EEVEE", "cartoon": "EEVEE"}},
    "draft": {"resolution": (540, 960), "eevee_samples": 16, "cycles_samples": 24, "motion_blur": True,
              "volumetrics": True, "engine": {"stylized_3d": "EEVEE", "cartoon": "EEVEE"}},
    "final": {"resolution": (1080, 1920), "eevee_samples": 64, "cycles_samples": 160, "motion_blur": True,
              "volumetrics": True, "engine": {"stylized_3d": "CYCLES", "cartoon": "EEVEE"}},
    "final_4k": {"resolution": (2160, 3840), "eevee_samples": 96, "cycles_samples": 200, "motion_blur": True,
                 "volumetrics": True, "engine": {"stylized_3d": "CYCLES", "cartoon": "EEVEE"}},
}
DEVICE_ORDER = ["OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"]


def detect_gpu(preferred: str = "AUTO") -> dict:
    """Enable the best Cycles compute device. Returns {"type": ..., "devices": [...]}."""
    info = {"type": "CPU", "devices": []}
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except (KeyError, AttributeError):
        return info
    order = DEVICE_ORDER if preferred in ("AUTO", "", None) else [preferred.upper()]
    if preferred and preferred.upper() == "CPU":
        return info
    for dev_type in order:
        try:
            prefs.compute_device_type = dev_type
        except TypeError:
            continue
        try:
            prefs.refresh_devices() if hasattr(prefs, "refresh_devices") else prefs.get_devices()
        except Exception:
            pass
        devices = [d for d in prefs.devices if d.type == dev_type]
        if devices:
            for d in prefs.devices:
                d.use = d.type in (dev_type, "CPU") if dev_type != "METAL" else d.type == dev_type
            info = {"type": dev_type, "devices": [d.name for d in devices]}
            return info
    try:
        prefs.compute_device_type = "NONE"
    except TypeError:
        pass
    return info


def configure(scene, preset: str, style: str, device: str = "AUTO", fps: int | None = None,
              volumetric_night: bool = False) -> dict:
    p = PRESETS.get(preset, PRESETS["draft"])
    engine_kind = p["engine"].get(style, "EEVEE")
    eid = compat.set_engine(scene, engine_kind)
    r = scene.render
    r.resolution_x, r.resolution_y = p["resolution"]
    r.resolution_percentage = 100
    r.pixel_aspect_x = r.pixel_aspect_y = 1.0
    if fps:
        r.fps = int(fps)
        r.fps_base = 1.0
    r.use_motion_blur = bool(p["motion_blur"])
    compat.set_props(r, motion_blur_shutter=0.5)
    r.film_transparent = False
    r.use_persistent_data = True if engine_kind == "CYCLES" else r.use_persistent_data
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.image_settings.color_depth = "8"
    compat.set_props(r.image_settings, compression=15)
    r.use_overwrite = False      # resumable: existing frames are skipped
    r.use_placeholder = True     # parallel workers never render the same frame twice
    info = {"engine": eid, "resolution": list(p["resolution"]), "device": "GPU(OpenGL/Vulkan)"}
    if compat.is_eevee(scene):
        ee = scene.eevee
        compat.set_props(ee, taa_render_samples=p["eevee_samples"], use_shadows=True,
                         shadow_ray_count=1 if preset in ("proxy", "draft") else 2,
                         shadow_step_count=4 if preset in ("proxy", "draft") else 8,
                         use_raytracing=preset not in ("proxy",), ray_tracing_method="SCREEN",
                         use_volumetric_shadows=volumetric_night and p["volumetrics"],
                         volumetric_tile_size="8" if preset != "proxy" else "16",
                         volumetric_samples=32 if preset.startswith("final") else 16,
                         use_gtao=True, gtao_distance=0.4, fast_gi_method="GLOBAL_ILLUMINATION",
                         use_fast_gi=True, clamp_surface_indirect=10.0)
    else:
        cy = scene.cycles
        gpu = detect_gpu(device)
        cy.device = "GPU" if gpu["type"] != "CPU" else "CPU"
        cy.samples = p["cycles_samples"]
        compat.set_props(cy, use_adaptive_sampling=True, adaptive_threshold=0.02, use_denoising=True,
                         denoiser="OPTIX" if gpu["type"] == "OPTIX" else "OPENIMAGEDENOISE",
                         denoising_input_passes="RGB_ALBEDO_NORMAL", max_bounces=6, diffuse_bounces=3,
                         glossy_bounces=3, transmission_bounces=4, volume_bounces=1, transparent_max_bounces=8,
                         caustics_reflective=False, caustics_refractive=False, blur_glossy=1.0,
                         sample_clamp_indirect=8.0, use_light_tree=True)
        info["device"] = f"{gpu['type']} {', '.join(gpu['devices'])}".strip()
    color_management(scene, style)
    return info


def color_management(scene, style: str) -> None:
    vs = scene.view_settings
    try:
        vs.view_transform = "AgX"
    except TypeError:
        vs.view_transform = "Filmic"
    looks = (["AgX - Punchy", "Punchy", "AgX - Medium High Contrast", "Medium High Contrast"] if style == "cartoon"
             else ["AgX - Medium High Contrast", "Medium High Contrast", "AgX - Base Contrast", "Base Contrast"])
    for look in looks:
        try:
            vs.look = look
            break
        except TypeError:
            continue
    vs.exposure = 0.0
    vs.gamma = 1.0
    scene.display_settings.display_device = "sRGB"
    compat.set_props(scene.sequencer_colorspace_settings, name="sRGB")
