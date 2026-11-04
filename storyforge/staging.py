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


MAX_CHEAT_YAW = 75.0      # bodies never turn further than this from the camera side (faces stay readable)
TURN_THRESHOLD = 70.0     # turn the body when a partner is further off than this (head + eyes can't cover it)
TURN_SECONDS = 0.35


def _yaw_diff(a: float, b: float) -> float:
    return (a - b + 180) % 360 - 180


def face_partners(paths: dict, locomotion: list[dict], timeline: dict, threshold: float = TURN_THRESHOLD,
                  turn_listeners: bool = True) -> list[dict]:
    """Conversation staging: a speaker whose addressee is far off their facing turns toward them at the
    start of the line (and the addressee toward the speaker), capped at +-MAX_CHEAT_YAW from the camera
    side so we never show the back of a head. Stationary characters only; walks keep their headings."""
    turns: list[dict] = []

    def moving(cid, t0, t1):
        return any(lo["character"] == cid and lo["start"] < t1 and lo["end"] > t0 for lo in locomotion)

    def pos(cid, t):
        keys = paths[cid]
        if t <= keys[0][0]:
            return keys[0][1], keys[0][2], keys[0][3]
        for a, b in zip(keys, keys[1:], strict=False):
            if a[0] <= t <= b[0]:
                u = 0.0 if b[0] == a[0] else (t - a[0]) / (b[0] - a[0])
                return (a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u, a[3] + _yaw_diff(b[3], a[3]) * u)
        return keys[-1][1], keys[-1][2], keys[-1][3]

    def turn(cid, other, t, dur):
        if cid not in paths or other not in paths or moving(cid, t - 0.1, t + dur):
            return
        x, y, yaw = pos(cid, t)
        ox, oy, _ = pos(other, t)
        want = yaw_towards((x, y), (ox, oy))
        if abs(_yaw_diff(want, yaw)) <= threshold:
            return
        new = max(-MAX_CHEAT_YAW, min(MAX_CHEAT_YAW, want))
        if abs(_yaw_diff(new, yaw)) < 12:
            return
        keys = paths[cid]
        if any(t < k[0] <= t + TURN_SECONDS for k in keys):  # a scripted turn/move already happens here
            return
        before = [k for k in keys if k[0] < t]
        after = [k for k in keys if k[0] > t + TURN_SECONDS]
        # keys that only hold the old facing (same spot, same yaw) take the new facing; stop at a
        # deliberate turn or at the next walk (its "turn into the walk" key keeps the walking heading)
        next_move = min((lo["start"] for lo in locomotion if lo["character"] == cid and lo["start"] >= t),
                        default=float("inf"))
        for k in after:
            if (k[0] > next_move + 1e-6 or math.dist((k[1], k[2]), (x, y)) > 0.01
                    or abs(_yaw_diff(k[3], yaw)) > 1.0):
                break
            k[3] = new
        paths[cid] = before + [[t, x, y, yaw], [t + TURN_SECONDS, x, y, new]] + after
        turns.append({"character": cid, "towards": other, "t": round(t, 3), "from": round(yaw, 1),
                      "to": round(new, 1)})

    for b in timeline.get("beats", []):
        spk, add = b.get("speaker"), b.get("addressee")
        if not spk or not add or add == spk or not (b.get("line") or "").strip():
            continue
        dur = float(b.get("end", b["start"] + 1.0)) - float(b["start"])
        if dur < 0.8:
            continue
        t = max(0.0, float(b["start"]) - 0.15)
        turn(spk, add, t, min(dur, 1.0))
        if turn_listeners:
            turn(add, spk, t + 0.1, min(dur, 1.0))
    return turns


def plan_blocking(timeline: dict, cast_registry: dict, location: dict, fixes: dict | None = None) -> dict:
    loc = get_location(location.get("preset", timeline["location"]))
    cast = timeline["cast"]
    n = len(cast)
    formation = loc["formations"].get(min(max(n, 1), 4), loc["formations"][1])
    if n > len(formation):  # more than 4: spread the rest along the back
        formation = list(formation) + [(-1.4 + 0.7 * k, 1.4, 0) for k in range(n - len(formation))]
    marks = dict(loc["marks"])
    paths: dict[str, list[list[float]]] = {}
    home: dict[str, tuple[float, float, float]] = {}
    spacing = float((fixes or {}).get("spacing", 1.0))  # quality auto-fix: bodies overlapped
    for cid, (x, y, yaw) in zip(cast, formation, strict=False):
        home[cid] = (x * spacing, y, yaw)
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
    fixes = fixes or {}
    turns = face_partners(paths, locomotion, timeline, threshold=float(fixes.get("turn_threshold", TURN_THRESHOLD)))
    metrics = {cid: body_metrics((cast_registry.get(cid) or {}).get("look", {}).get("body"))
               for cid in cast}

    def top_extra(cid: str) -> float:
        """Hair / hats rise above the head box: framing must leave room for them."""
        look = (cast_registry.get(cid) or {}).get("look", {}) or {}
        style = (look.get("hair") or {}).get("style", "short")
        hats = {a.get("type") for a in look.get("accessories") or [] if isinstance(a, dict)}
        extra = {"spiky": 0.3, "bun": 0.22, "curly": 0.18, "ponytail": 0.06, "bob": 0.06}.get(style, 0.06)
        if hats & {"beanie", "cap"}:
            extra = max(extra, 0.3)
        if "goggles" in hats:
            extra = max(extra, 0.12)
        return extra * metrics[cid]["head_size"]
    return {"location": loc["preset"], "home": {c: list(v) for c, v in home.items()},
            "paths": paths, "locomotion": locomotion, "turns": turns, "marks": {k: list(v) for k, v in marks.items()},
            "heights": {c: {"head_center": m["head_center"], "eye_z": m["eye_z"], "head_top": m["head_top"],
                            "chest_z": m["chest_z"], "hip_z": m["hip_z"], "head_size": m["head_size"],
                            "shoulder_z": m["shoulder_z"], "knee_z": m["knee_z"], "mouth_z": m["mouth_z"],
                            "neck_base": m["neck_base"], "top": m["head_top"] + top_extra(c)}
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
