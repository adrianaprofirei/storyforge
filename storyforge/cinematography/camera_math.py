"""Camera math for vertical 9:16 frames.

Lens convention: focal lengths are full-frame equivalents with the 36 mm side of the sensor
along the *vertical* axis (a full-frame camera turned to portrait, cropped to 9:16). So a 50 mm
lens has a 39.6 deg vertical FOV, 24 mm is genuinely wide and 85 mm a tight portrait lens.
Blender cameras are set to sensor_fit=VERTICAL, sensor_height=36 accordingly.

Coordinates: Z up, characters face -Y, the audience side is -Y.
"""

from __future__ import annotations

import math

SENSOR_V = 36.0
ASPECT = 9.0 / 16.0  # width / height


def vfov(lens_mm: float) -> float:
    return 2 * math.atan(SENSOR_V / 2 / lens_mm)


def hfov(lens_mm: float) -> float:
    return 2 * math.atan(math.tan(vfov(lens_mm) / 2) * ASPECT)


def distance_for_span(span_v: float, lens_mm: float) -> float:
    """Distance at which a vertical span (m) exactly fills the frame height."""
    return (span_v / 2) / math.tan(vfov(lens_mm) / 2)


def span_at(distance: float, lens_mm: float) -> tuple[float, float]:
    """(width, height) in metres of the frame at a distance."""
    h = 2 * distance * math.tan(vfov(lens_mm) / 2)
    return h * ASPECT, h


def norm2(v):
    n = math.hypot(v[0], v[1]) or 1.0
    return (v[0] / n, v[1] / n)


def rot2(v, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def cross2(a, b) -> float:
    return a[0] * b[1] - a[1] * b[0]


def audience_side_sign(a: tuple, b: tuple, audience=(0.0, -6.0)) -> float:
    """Sign of the audience side relative to the line a->b (2D)."""
    return math.copysign(1.0, cross2((b[0] - a[0], b[1] - a[1]), (audience[0] - a[0], audience[1] - a[1])) or 1.0)


def on_audience_side(a: tuple, b: tuple, cam: tuple, audience=(0.0, -6.0)) -> bool:
    """180-degree rule: camera must be on the same side of the action line a-b as the audience."""
    s_cam = cross2((b[0] - a[0], b[1] - a[1]), (cam[0] - a[0], cam[1] - a[1]))
    return s_cam * audience_side_sign(a, b, audience) > 0


def look_rotation(cam: tuple, target: tuple) -> tuple[float, float, float]:
    """Blender camera euler XYZ (radians) looking from cam to target (camera looks down -Z, up +Y)."""
    dx, dy, dz = target[0] - cam[0], target[1] - cam[1], target[2] - cam[2]
    horiz = math.hypot(dx, dy)
    pitch = math.atan2(dz, horiz)  # + looking up
    yaw = math.atan2(dy, dx)
    # camera rest looks down -Z; rotate X by 90deg to look along +Y, then yaw around Z
    return (math.pi / 2 + pitch, 0.0, yaw - math.pi / 2)


def compose_target(eye: tuple, cam: tuple, lens_mm: float, screen_x: float, screen_y: float) -> tuple:
    """Aim point so that `eye` lands at normalised screen position (screen_x, screen_y);
    (0.5, 0.5) is the centre, y measured from the bottom."""
    dx, dy, dz = eye[0] - cam[0], eye[1] - cam[1], eye[2] - cam[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    w, h = span_at(dist, lens_mm)
    fwd = (dx / dist, dy / dist, dz / dist)
    right = norm2((fwd[1], -fwd[0]))
    off_r = (screen_x - 0.5) * w
    off_u = (screen_y - 0.5) * h
    # shift aim opposite to the desired screen offset
    return (eye[0] - right[0] * off_r, eye[1] - right[1] * off_r, eye[2] - off_u)


# shot size: vertical span of the frame expressed in head sizes (h = head size) + anchor
SHOT_SPANS = {
    "extreme_close_up": 1.05,
    "close_up": 2.0,
    "medium_close": 3.0,
    "medium": 4.2,
    "medium_wide": 5.6,
    "wide": 8.5,
    "establishing_wide": 13.0,
    "two_shot": 4.8,
    "over_the_shoulder": 3.3,
    "insert": 1.3,
}
SHOT_SIZE_ORDER = ["extreme_close_up", "close_up", "medium_close", "over_the_shoulder", "medium", "two_shot",
                   "medium_wide", "wide", "establishing_wide"]
DEFAULT_LENS = {
    "establishing_wide": 24, "wide": 28, "medium_wide": 32, "two_shot": 35, "medium": 40,
    "over_the_shoulder": 50, "medium_close": 50, "close_up": 65, "extreme_close_up": 85, "insert": 60,
}
DEFAULT_FSTOP = {
    "establishing_wide": 8.0, "wide": 5.6, "medium_wide": 4.0, "two_shot": 4.0, "medium": 2.8,
    "over_the_shoulder": 2.4, "medium_close": 2.2, "close_up": 2.0, "extreme_close_up": 2.0, "insert": 2.8,
}
# where the subject's eyes sit vertically (from the bottom) per shot size; tighter -> higher (headroom)
EYE_LINE = {
    "extreme_close_up": 0.56, "close_up": 0.62, "medium_close": 0.66, "over_the_shoulder": 0.66,
    "medium": 0.68, "two_shot": 0.67, "medium_wide": 0.70, "wide": 0.66, "establishing_wide": 0.6, "insert": 0.5,
}


def size_index(shot_type: str) -> int:
    return SHOT_SIZE_ORDER.index(shot_type) if shot_type in SHOT_SIZE_ORDER else 4
