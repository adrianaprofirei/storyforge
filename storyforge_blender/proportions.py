"""Body proportions of the procedural blocky toy figure (pure Python, shared with the backend).

All values in metres. The figure faces -Y, stands on z=0, origin between the feet.
`body` keys (all multipliers, default 1.0): height, head_size, torso_width, torso_depth,
torso_length, limb_thickness, leg_length, arm_length.
"""

from __future__ import annotations


def body_metrics(body: dict | None) -> dict:
    b = {k: float(v) for k, v in (body or {}).items()}
    h = b.get("height", 1.0)
    head = 0.345 * b.get("head_size", 1.0) * (0.92 + 0.08 * h)
    limb = 0.085 * b.get("limb_thickness", 1.0) * (0.9 + 0.1 * h)
    leg_len = 0.37 * b.get("leg_length", 1.0) * h
    torso_len = 0.285 * b.get("torso_length", 1.0) * h
    torso_w = 0.32 * b.get("torso_width", 1.0) * (0.9 + 0.1 * h)
    torso_d = 0.19 * b.get("torso_depth", 1.0) * (0.9 + 0.1 * h)
    arm_len = 0.40 * b.get("arm_length", 1.0) * h
    foot_h = 0.065 * (0.9 + 0.1 * h)
    ankle_z = foot_h
    knee_z = ankle_z + leg_len * 0.48
    hip_z = ankle_z + leg_len
    pelvis_h = 0.09 * h
    torso_base = hip_z + pelvis_h * 0.35
    chest_z = torso_base + torso_len * 0.55
    shoulder_z = torso_base + torso_len * 0.88
    neck_base = torso_base + torso_len
    neck_h = 0.035 * h
    head_base = neck_base + neck_h
    head_center = head_base + head * 0.5
    head_top = head_base + head
    hip_x = torso_w * 0.24
    shoulder_x = torso_w * 0.5 + limb * 0.52
    return {
        "scale_h": h,
        "head_size": head,
        "limb": limb,
        "foot_height": foot_h,
        "foot_length": 0.19 * (0.9 + 0.1 * h) * b.get("leg_length", 1.0) ** 0.3,
        "ankle_z": ankle_z,
        "knee_z": knee_z,
        "hip_z": hip_z,
        "hip_x": hip_x,
        "pelvis_h": pelvis_h,
        "torso_base": torso_base,
        "torso_len": torso_len,
        "torso_w": torso_w,
        "torso_d": torso_d,
        "chest_z": chest_z,
        "shoulder_z": shoulder_z,
        "shoulder_x": shoulder_x,
        "neck_base": neck_base,
        "neck_h": neck_h,
        "head_base": head_base,
        "head_center": head_center,
        "eye_z": head_base + head * 0.52,
        "mouth_z": head_base + head * 0.27,
        "head_top": head_top,
        "total_height": head_top,
        "upper_arm": arm_len * 0.45,
        "forearm": arm_len * 0.40,
        "hand": arm_len * 0.18,
        "arm_len": arm_len,
        "thigh": leg_len * 0.52,
        "shin": leg_len * 0.48,
    }
