"""Blocking: where every character stands (and walks) over time.

Characters start in the location's formation for the cast size. `motion` events move them
between marks (enter from a side, walk/run/tiptoe to a mark, exit). The result is a per
character list of path keys [(t, x, y, yaw)], consumed by the shot designer (framing, the
180-degree line, eyelines) and by Blender (root motion + locomotion clips).
"""

from __future__ import annotations

import math

from storyforge_blender.locations_data import get_location
from storyforge_blender.proportions import body_metrics

WALK_SPEED = {"walk_to": 0.9, "run_to": 2.1, "tiptoe_to": 0.45, "enter": 0.9, "exit": 1.0}


def yaw_towards(src: tuple[float, float], dst: tuple[float, float]) -> float:
    """Yaw (deg) so a character at src faces dst (yaw 0 faces -Y, +90 faces +X)."""
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    return math.degrees(math.atan2(dx, -dy))


def plan_blocking(timeline: dict, cast_registry: dict, location: dict) -> dict:
    loc = get_location(location.get("preset", timeline["location"]))
    cast = timeline["cast"]
    n = len(cast)
    formation = loc["formations"].get(min(max(n, 1), 4), loc["formations"][1])
    if n > len(formation):  # more than 4: spread the rest along the back
        formation = list(formation) + [(-1.4 + 0.7 * k, 1.4, 0) for k in range(n - len(formation))]
    marks = dict(loc["marks"])
    paths: dict[str, list[list[float]]] = {}
    home: dict[str, tuple[float, float, float]] = {}
    for cid, (x, y, yaw) in zip(cast, formation, strict=False):
        home[cid] = (x, y, yaw)
    # characters whose first motion is an `enter` start off-screen
    first_motion: dict[str, dict] = {}
    for ev in timeline["events"]:
        if ev["type"] == "motion" and ev["character"] not in first_motion:
            first_motion[ev["character"]] = ev
    for cid in cast:
        hx, hy, hyaw = home[cid]
        ev = first_motion.get(cid)
        if ev and ev["motion"] == "enter":
            side = ev.get("side") or ("left" if hx < 0 else "right")
            sx, sy = marks.get(f"offscreen_{side}", (-4.5 if side == "left" else 4.5, hy))
            paths[cid] = [[0.0, sx, sy, yaw_towards((sx, sy), (hx, hy))]]
        elif ev and ev["motion"] in ("tiptoe_to", "walk_to", "run_to") and (ev.get("to") in (None, "center", "home")):
            # group moves forward into the formation from behind
            sx, sy = hx * 0.9, hy + 1.6
            paths[cid] = [[0.0, sx, sy, yaw_towards((sx, sy), (hx, hy))]]
        else:
            paths[cid] = [[0.0, hx, hy, hyaw]]
    locomotion: list[dict] = []
    for ev in timeline["events"]:
        if ev["type"] != "motion":
            continue
        cid = ev["character"]
        if cid not in paths:
            continue
        cur = paths[cid][-1]
        t0 = max(ev["t"], cur[0])
        kind = ev["motion"]
        hx, hy, hyaw = home[cid]
        if kind in ("enter",) or (kind in ("walk_to", "run_to", "tiptoe_to") and ev.get("to") in (None, "center", "home")):
            target = (hx, hy)
        elif kind == "exit":
            side = ev.get("side") or ("left" if cur[1] < 0 else "right")
            target = marks.get(f"offscreen_{side}", (-5.0, cur[2]))
        elif kind in ("walk_to", "run_to", "tiptoe_to"):
            target = marks.get(ev.get("to") or "", None)
            if target is None:
                other = paths.get(ev.get("to") or "")
                target = (other[-1][1] * 0.7 + cur[1] * 0.3, other[-1][2]) if other else (hx, hy)
        elif kind == "turn_to":
            other = paths.get(ev.get("to") or "")
            if other:
                paths[cid].append([t0, cur[1], cur[2], cur[3]])
                paths[cid].append([t0 + 0.4, cur[1], cur[2], yaw_towards((cur[1], cur[2]), (other[-1][1], other[-1][2]))])
            continue
        else:  # sit / stand: in place
            locomotion.append({"character": cid, "kind": kind, "start": t0, "end": t0 + 1.0})
            continue
        dist = math.dist((cur[1], cur[2]), target)
        speed = WALK_SPEED.get(kind, 0.9)
        dur = max(0.6, dist / speed)
        heading = yaw_towards((cur[1], cur[2]), target)
        paths[cid].append([t0, cur[1], cur[2], cur[3]])
        paths[cid].append([t0 + 0.25, cur[1], cur[2], heading])  # turn into the walk
        paths[cid].append([t0 + dur, target[0], target[1], heading])
        end_yaw = hyaw if target == (hx, hy) else heading
        paths[cid].append([t0 + dur + 0.35, target[0], target[1], end_yaw])
        locomotion.append({"character": cid, "kind": kind, "start": t0, "end": t0 + dur, "distance": dist,
                           "from": [cur[1], cur[2]], "to": list(target)})
    metrics = {cid: body_metrics((cast_registry.get(cid) or {}).get("look", {}).get("body"))
               for cid in cast}
    return {"location": loc["preset"], "home": {c: list(v) for c, v in home.items()},
            "paths": paths, "locomotion": locomotion, "marks": {k: list(v) for k, v in marks.items()},
            "heights": {c: {"head_center": m["head_center"], "eye_z": m["eye_z"], "head_top": m["head_top"],
                            "chest_z": m["chest_z"], "hip_z": m["hip_z"], "head_size": m["head_size"]}
                        for c, m in metrics.items()},
            "surfaces": {k: list(v) for k, v in loc.get("surfaces", {}).items()}}


def position_at(blocking: dict, cid: str, t: float) -> tuple[float, float, float]:
    keys = blocking["paths"][cid]
    if t <= keys[0][0]:
        return keys[0][1], keys[0][2], keys[0][3]
    for a, b in zip(keys, keys[1:], strict=False):
        if a[0] <= t <= b[0]:
            u = 0.0 if b[0] == a[0] else (t - a[0]) / (b[0] - a[0])
            u = u * u * (3 - 2 * u)  # ease in/out
            yaw = a[3] + ((b[3] - a[3] + 180) % 360 - 180) * u
            return a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u, yaw
    k = keys[-1]
    return k[1], k[2], k[3]


def head_point(blocking: dict, cid: str, t: float) -> tuple[float, float, float]:
    x, y, _ = position_at(blocking, cid, t)
    return x, y, blocking["heights"][cid]["eye_z"]


def is_moving(blocking: dict, cid: str, t0: float, t1: float) -> bool:
    for lo in blocking["locomotion"]:
        if lo["character"] == cid and lo["start"] < t1 and lo["end"] > t0 and lo.get("distance", 0) > 0.05:
            return True
    return False
