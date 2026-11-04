"""Lighting design: time-of-day presets + a per-shot three-point rig.

The base light of a location (sun/moon, sky, practicals, volumetrics) comes from the time of day
and the location (interior/exterior). On top of it every shot gets a key/fill/rim rig placed
relative to the camera and the subject, motivated by the location's main light direction:
* key  at 35-50 deg off the camera axis on the motivated side, ~32 deg up,
* fill opposite the key, low and soft, key:fill ratio from the mood (2.5:1 bright .. 6:1 night/drama),
* rim  behind the subject on the side opposite the key, light-linked to characters only so it
  separates them from the background without lighting the set.
"""

from __future__ import annotations

import math

from storyforge.cinematography.camera_math import norm2, rot2

# colour temperatures (approx. sRGB) for light colours
KELVIN = {
    2700: (1.0, 0.72, 0.42), 3200: (1.0, 0.79, 0.56), 4000: (1.0, 0.86, 0.71), 4500: (1.0, 0.89, 0.77),
    5200: (1.0, 0.94, 0.88), 5600: (1.0, 0.96, 0.92), 6500: (1.0, 1.0, 1.0), 8000: (0.84, 0.9, 1.0),
    10000: (0.74, 0.83, 1.0),
}

TIME_PRESETS = {
    #            sun_k  sun_elev sun_strength sky_top     sky_bottom  world_str key_k  ratio  rim_k  vol
    "morning":   (5200, 18, 3.0, "#9CC9EB", "#F6E3C8", 0.55, 5200, 2.8, 4000, 0.0),
    "day":       (5600, 55, 4.0, "#7DB6E8", "#E6F0F7", 0.65, 5600, 2.5, 6500, 0.0),
    "afternoon": (4500, 32, 3.5, "#8DBBE0", "#F5D7B2", 0.5, 4500, 3.0, 3200, 0.004),
    "sunset":    (3200, 8, 3.0, "#5B5E9E", "#F59E6B", 0.4, 3200, 3.5, 2700, 0.006),
    "evening":   (8000, 25, 0.4, "#1E2A5A", "#45507E", 0.18, 3200, 4.0, 8000, 0.008),
    "night":     (10000, 42, 0.9, "#0B1030", "#1B2347", 0.1, 8000, 5.0, 10000, 0.02),
}
EMOTION_CONTRAST = {"scared": 1.4, "sad": 1.25, "angry": 1.3, "shocked": 1.2, "happy": 0.85, "excited": 0.85}


def base_lighting(location: dict, time_of_day: str, interior: bool) -> dict:
    sun_k, elev, sun_str, top, bottom, world, key_k, ratio, rim_k, vol = TIME_PRESETS.get(
        time_of_day, TIME_PRESETS["day"])
    az = location.get("key_dir", 40.0)
    return {
        "time_of_day": time_of_day,
        "world": {"top": top, "bottom": bottom, "strength": world * (0.7 if interior else 1.0)},
        "sun": {"azimuth": az + (180 if interior else 0), "elevation": elev, "color": KELVIN[sun_k],
                "strength": sun_str * (0.8 if interior else 1.0), "angle": 2.0 if time_of_day != "night" else 1.0},
        "volumetrics": {"density": vol, "anisotropy": 0.55, "color": KELVIN[rim_k]} if vol > 0 else None,
        "key_color": KELVIN[key_k], "rim_color": KELVIN[rim_k], "ratio": ratio,
        "night": time_of_day in ("night", "evening"),
    }


def shot_rig(shot: dict, beat: dict | None, base: dict, location: dict) -> dict:
    cam = shot["camera"]["position"]
    subj = shot["camera"]["focus_point"]
    to_cam = norm2((cam[0] - subj[0], cam[1] - subj[1]))
    motivated = location.get("key_dir", 40.0)
    # choose the key side closest to the motivated direction (stable within a scene)
    side = 1 if math.sin(math.radians(motivated)) >= 0 else -1
    key_off = 42 if shot["type"] not in ("close_up", "extreme_close_up") else 38
    key_dir = rot2(to_cam, side * key_off)
    fill_dir = rot2(to_cam, -side * 50)
    rim_dir = rot2(to_cam, -side * 155)
    ratio = base["ratio"]
    if beat:
        ratio *= EMOTION_CONTRAST.get(beat.get("emotion"), 1.0) ** (0.5 + float(beat.get("intensity", 0.5)))
    size_scale = {"establishing_wide": 2.2, "wide": 1.8, "medium_wide": 1.4}.get(shot["type"], 1.0)
    dist = 2.4 * size_scale
    key_energy = 320.0 * size_scale ** 2
    hz = subj[2]

    def place(d, elev_deg, r):
        e = math.radians(elev_deg)
        return [subj[0] + d[0] * r * math.cos(e), subj[1] + d[1] * r * math.cos(e), hz + r * math.sin(e)]

    rim_boost = 1.6 if base["night"] else 1.15
    return {
        "key": {"position": place(key_dir, 32, dist), "target": subj, "energy": round(key_energy, 1),
                "color": base["key_color"], "size": 1.1 * size_scale},
        "fill": {"position": place(fill_dir, 12, dist * 1.2), "target": subj,
                 "energy": round(key_energy / ratio * 1.44, 1), "color": _cooler(base["key_color"]) if not base["night"]
                 else (1.0, 0.8, 0.6), "size": 2.2 * size_scale},
        "rim": {"position": place(rim_dir, 40, dist * 0.9), "target": [subj[0], subj[1], hz + 0.05],
                "energy": round(key_energy * rim_boost, 1), "color": base["rim_color"], "size": 0.5 * size_scale},
    }


def _cooler(c):
    return (c[0] * 0.92, c[1] * 0.97, min(1.0, c[2] * 1.08))
