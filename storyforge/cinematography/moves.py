"""Camera movement -> keyframes (location, rotation, lens) and focus distance keys.

push_in   slow dolly toward the subject (8-18 % of the distance, ease-in-out)
pull_out  the reverse
dolly     lateral/forward reveal move along the camera's right vector
drift     subtle 3-5 % creep so no shot is ever a dead static frame
handheld  low-frequency smoothed noise on rotation/position (seeded, per frame)
whip_pan  starts rotated ~40 deg away and whips onto the framing in 6 frames (motion blur sells it)
snap_zoom fast lens change (x1.6) in 4 frames at the start of the shot
crane_up  rises 0.6-1 m while tilting to keep the subject
orbit     slow arc around the subject (<= 15 deg, stays on the audience side)
"""

from __future__ import annotations

import math
import random

from storyforge.cinematography.camera_math import look_rotation, norm2


def _lerp(a, b, u):
    return [a[i] + (b[i] - a[i]) * u for i in range(len(a))]


def _ease(u):
    return u * u * (3 - 2 * u)


def _frame(t: float, fps: int, fs: int) -> int:
    return fs + int(round(t * fps))


def camera_keys(shot: dict, fps: int, frame_start: int = 1, seed: int = 0) -> list[dict]:
    cam = shot["camera"]
    pos = list(cam["position"])
    tgt = list(cam["target"])
    lens = float(shot["lens_mm"])
    mv = shot.get("movement", {}).get("type", "static")
    amt = float(shot.get("movement", {}).get("amount", 1.0))
    f0 = _frame(shot["start"], fps, frame_start)
    f1 = max(f0 + 1, _frame(shot["end"], fps, frame_start))
    fwd = [tgt[i] - pos[i] for i in range(3)]
    dist = math.sqrt(sum(c * c for c in fwd)) or 1.0
    fwd_n = [c / dist for c in fwd]
    right = norm2((fwd_n[1], -fwd_n[0]))

    def key(f, p, t, ln):
        return {"frame": f, "location": [round(c, 5) for c in p], "rotation": [round(r, 6) for r in look_rotation(p, t)],
                "lens": round(ln, 3)}

    if mv in ("static",):
        return [key(f0, pos, tgt, lens)]
    if mv in ("push_in", "pull_out", "drift"):
        frac = {"push_in": 0.08 + 0.1 * amt, "pull_out": 0.08 + 0.1 * amt, "drift": 0.035}[mv]
        closer = [pos[i] + fwd_n[i] * dist * frac for i in range(3)]
        a, b = (closer, pos) if mv == "pull_out" else (pos, closer)
        return [key(f0, a, tgt, lens), key(f1, b, tgt, lens)]
    if mv == "dolly":
        off = 0.35 * amt
        a = [pos[0] - right[0] * off, pos[1] - right[1] * off, pos[2]]
        b = [pos[0] + right[0] * off * 0.4 + fwd_n[0] * dist * 0.06, pos[1] + right[1] * off * 0.4 + fwd_n[1] * dist * 0.06, pos[2]]
        return [key(f0, a, tgt, lens), key(f1, b, tgt, lens)]
    if mv == "crane_up":
        a = [pos[0], pos[1], pos[2] - 0.35]
        b = [pos[0] - fwd_n[0] * 0.3, pos[1] - fwd_n[1] * 0.3, pos[2] + 0.75 * amt]
        return [key(f0, a, tgt, lens), key(f1, b, tgt, lens)]
    if mv == "orbit":
        ang = math.radians(12 * amt)
        keys = []
        n = 4
        for k in range(n + 1):
            u = k / n
            a = -ang / 2 + ang * u
            vx, vy = pos[0] - tgt[0], pos[1] - tgt[1]
            p = [tgt[0] + vx * math.cos(a) - vy * math.sin(a), tgt[1] + vx * math.sin(a) + vy * math.cos(a), pos[2]]
            keys.append(key(f0 + int((f1 - f0) * u), p, tgt, lens))
        return keys
    if mv == "whip_pan":
        n_whip = min(6, max(3, (f1 - f0) // 3))
        side = 1 if (seed % 2) else -1
        ang = math.radians(42) * side
        vx, vy = tgt[0] - pos[0], tgt[1] - pos[1]
        t_start = [pos[0] + vx * math.cos(ang) - vy * math.sin(ang), pos[1] + vx * math.sin(ang) + vy * math.cos(ang), tgt[2]]
        keys = [key(f0, pos, t_start, lens)]
        for k in range(1, n_whip + 1):
            u = _ease(k / n_whip) ** 0.8
            keys.append(key(f0 + k, pos, _lerp(t_start, tgt, u), lens))
        settle = _lerp(tgt, t_start, -0.02)  # tiny overshoot then settle
        keys.append(key(f0 + n_whip + 2, pos, settle, lens))
        keys.append(key(f0 + n_whip + 5, pos, tgt, lens))
        if f1 > f0 + n_whip + 6:
            keys.append(key(f1, [pos[i] + fwd_n[i] * dist * 0.03 for i in range(3)], tgt, lens))
        return keys
    if mv == "snap_zoom":
        z0 = lens / 1.6
        n = min(5, max(3, (f1 - f0) // 4))
        keys = [key(f0, pos, tgt, z0)]
        for k in range(1, n + 1):
            keys.append(key(f0 + k, pos, tgt, z0 + (lens * 1.04 - z0) * _ease(k / n)))
        keys.append(key(f0 + n + 3, pos, tgt, lens))
        if f1 > f0 + n + 4:
            keys.append(key(f1, [pos[i] + fwd_n[i] * dist * 0.025 for i in range(3)], tgt, lens))
        return keys
    if mv == "handheld":
        rng = random.Random(seed * 7919 + f0)
        freqs = [(rng.uniform(0.35, 0.7), rng.uniform(0, 6.28)) for _ in range(3)]
        freqs2 = [(rng.uniform(1.1, 1.9), rng.uniform(0, 6.28)) for _ in range(3)]
        scale = 0.012 * (0.5 + amt)
        keys = []
        step = 2
        for f in range(f0, f1 + 1, step):
            t = (f - f0) / fps
            off = [scale * (math.sin(2 * math.pi * a * t + p) + 0.35 * math.sin(2 * math.pi * a2 * t + p2))
                   for (a, p), (a2, p2) in zip(freqs, freqs2, strict=False)]
            p = [pos[0] + off[0] * 0.4, pos[1] + off[1] * 0.4, pos[2] + off[2] * 0.3]
            tt = [tgt[0] + off[1] * 0.9, tgt[1], tgt[2] + off[0] * 0.7]
            keys.append(key(f, p, tt, lens))
        return keys
    return [key(f0, pos, tgt, lens)]


def focus_keys(shot: dict, blocking: dict, fps: int, frame_start: int, head_point_fn, cam_keys: list[dict]) -> list[dict]:
    """Focus distance from the camera to the focused character's eyes, with pulls on speaker changes."""
    from storyforge.cinematography.camera_math import look_rotation  # noqa: F401

    f0, f1 = cam_keys[0]["frame"], max(cam_keys[-1]["frame"], _frame(shot["end"], fps, frame_start))
    subject = shot["focus"]["subject"]
    pulls = shot["focus"].get("pulls", [])
    times = sorted({shot["start"], shot["end"]} | {p["t"] for p in pulls} | {p["t"] + p.get("duration", 0.4) for p in pulls})
    out = []
    cur = subject
    for t in times:
        for p in pulls:
            if p["t"] + p.get("duration", 0.4) <= t + 1e-6:
                cur = p["to"]
        f = _frame(t, fps, frame_start)
        f = max(f0, min(f1, f))
        cam = _cam_at(cam_keys, f)
        if shot["type"] == "insert":
            pt = shot["camera"]["focus_point"]
        else:
            pt = head_point_fn(blocking, cur, t)
        d = math.dist(cam, pt)
        out.append({"frame": f, "distance": round(max(0.1, d), 4)})
    dedup = {}
    for k in out:
        dedup[k["frame"]] = k
    return [dedup[f] for f in sorted(dedup)]


def _cam_at(keys: list[dict], f: int) -> list[float]:
    if f <= keys[0]["frame"]:
        return keys[0]["location"]
    for a, b in zip(keys, keys[1:], strict=False):
        if a["frame"] <= f <= b["frame"]:
            u = (f - a["frame"]) / max(1, b["frame"] - a["frame"])
            return _lerp(a["location"], b["location"], u)
    return keys[-1]["location"]
