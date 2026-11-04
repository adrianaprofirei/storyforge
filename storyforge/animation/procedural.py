"""Built-in procedural animation clips (original work, CC0) in the canonical clip format.

Convention (see storyforge_blender/posing.py): for every bone a quaternion L in rest-pose armature
axes relative to the parent; rest pose = T-pose; armature axes: +X = character's left, -Y = forward,
+Z = up. Clips are authored as timed key poses with easing (anticipation and overshoot are
authored into the keys) and sampled per frame. Gestures start and end on the relaxed base pose so
NLA blend-in/out is seamless. Mocap clips with the same tag override these (see library.py).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from storyforge.animation import quat as Q
from storyforge_blender.proportions import body_metrics

FPS = 30
Pose = dict[str, Q.Q]
HIP_H = body_metrics(None)["hip_z"]  # default figure hip height: clip root offsets are relative to it


# ------------------------------------------------------------------ pose helpers (armature axes)
def arm(side: str, down: float = 72, fwd: float = 8, twist: float = 0.0) -> Pose:
    """Upper arm pointing `down` degrees below horizontal and swung `fwd` degrees forward."""
    d, f = math.radians(down), math.radians(fwd)
    direction = (math.cos(d) * math.cos(f), -math.cos(d) * math.sin(f), -math.sin(d))
    q = Q.between((1.0, 0.0, 0.0), direction)
    if twist:
        q = Q.mul(Q.axis_angle(direction, twist), q)
    if side == "R":
        q = Q.mirror(q)
    return {f"upper_arm.{side}": q}


def elbow(side: str, bend: float, twist: float = 0.0) -> Pose:
    q = Q.axis_angle("Z", -bend)
    if twist:
        q = Q.mul(Q.axis_angle("X", twist), q)
    return {f"forearm.{side}": Q.mirror(q) if side == "R" else q}


def wrist(side: str, flex: float = 0.0, dev: float = 0.0) -> Pose:
    q = Q.mul(Q.axis_angle("Y", dev), Q.axis_angle("Z", -flex))
    return {f"hand.{side}": Q.mirror(q) if side == "R" else q}


def shoulder(side: str, up: float = 0.0, fwd: float = 0.0) -> Pose:
    q = Q.mul(Q.axis_angle("Z", -fwd), Q.axis_angle("Y", -up))
    return {f"shoulder.{side}": Q.mirror(q) if side == "R" else q}


def leg(side: str, flex: float = 0.0, abduct: float = 0.0, twist: float = 0.0) -> Pose:
    q = Q.mul(Q.axis_angle("Z", twist), Q.mul(Q.axis_angle("Y", -abduct), Q.axis_angle("X", -flex)))
    return {f"thigh.{side}": Q.mirror(q) if side == "R" else q}


def knee(side: str, bend: float) -> Pose:
    return {f"shin.{side}": Q.axis_angle("X", bend)}


def ankle(side: str, toes_up: float) -> Pose:
    return {f"foot.{side}": Q.axis_angle("X", -toes_up)}


def spine(fwd: float = 0.0, side: float = 0.0, twist: float = 0.0, split: float = 0.5) -> Pose:
    return {"spine": Q.euler(fwd * (1 - split), side * (1 - split), twist * (1 - split)),
            "chest": Q.euler(fwd * split, side * split, twist * split)}


def head(nod: float = 0.0, turn: float = 0.0, tilt: float = 0.0, neck_share: float = 0.3) -> Pose:
    return {"neck": Q.euler(nod * neck_share, tilt * neck_share, turn * neck_share),
            "head": Q.euler(nod * (1 - neck_share), tilt * (1 - neck_share), turn * (1 - neck_share))}


def both(fn: Callable[..., Pose], *a, **kw) -> Pose:
    return {**fn("L", *a, **kw), **fn("R", *a, **kw)}


def merge(*poses: Pose) -> Pose:
    out: Pose = {}
    for p in poses:
        for k, v in p.items():
            out[k] = Q.mul(out[k], v) if k in out else v
    return out


RELAXED: Pose = merge(arm("L", 72, 8), arm("R", 72, 8), elbow("L", 12), elbow("R", 12), shoulder("L", 2),
                      shoulder("R", 2))
UPPER_BONES = ["spine", "chest", "neck", "head", "shoulder.L", "shoulder.R", "upper_arm.L", "upper_arm.R",
               "forearm.L", "forearm.R", "hand.L", "hand.R"]
LEG_BONES = ["thigh.L", "thigh.R", "shin.L", "shin.R", "foot.L", "foot.R"]


def relaxed(*overrides: Pose) -> Pose:
    p = dict(RELAXED)
    for o in overrides:
        p.update(o)
    return p


# ------------------------------------------------------------------ easing + sampling
def ease(kind: str, u: float) -> float:
    u = max(0.0, min(1.0, u))
    if kind == "linear":
        return u
    if kind == "in":
        return u * u
    if kind == "out":
        return 1 - (1 - u) * (1 - u)
    if kind == "back":  # overshoot then settle
        c = 1.70158
        return 1 + (c + 1) * (u - 1) ** 3 + c * (u - 1) ** 2
    if kind == "snap":
        return 1 - (1 - u) ** 4
    return u * u * (3 - 2 * u)  # smooth


@dataclass
class Key:
    t: float
    pose: Pose
    root: tuple[float, float, float] = (0.0, 0.0, 0.0)
    ease: str = "smooth"


@dataclass
class ClipDef:
    name: str
    duration: float
    keys: list[Key]
    tags: list[str] = field(default_factory=list)
    loop: bool = False
    bones: list[str] | None = None
    contacts: dict[str, list[tuple[float, float]]] | None = None  # seconds
    stride: float | None = None  # metres per cycle (locomotion)
    squash: list[tuple[float, float]] | None = None  # (t, scale_z) keys for squash & stretch
    category: str = "gesture"


def sample(cd: ClipDef, fps: int = FPS) -> dict:
    n = max(2, int(round(cd.duration * fps)) + (0 if cd.loop else 1))
    bones = cd.bones or sorted({b for k in cd.keys for b in k.pose})
    keys = sorted(cd.keys, key=lambda k: k.t)
    if cd.loop and keys[-1].t < cd.duration:
        keys = keys + [Key(cd.duration, keys[0].pose, keys[0].root, keys[0].ease)]
    out_bones = {b: [] for b in bones}
    root = []
    for i in range(n):
        t = i / fps
        j = 0
        while j < len(keys) - 2 and keys[j + 1].t <= t:
            j += 1
        a, b = keys[j], keys[min(j + 1, len(keys) - 1)]
        span = max(1e-6, b.t - a.t)
        u = ease(b.ease, (t - a.t) / span) if t >= a.t else 0.0
        for bn in bones:
            qa = a.pose.get(bn, RELAXED.get(bn, Q.IDENTITY))
            qb = b.pose.get(bn, RELAXED.get(bn, Q.IDENTITY))
            q = Q.slerp(qa, qb, min(max(u, 0.0), 1.0)) if b.ease != "back" else _slerp_ext(qa, qb, u)
            out_bones[bn].append(Q.rounded(q))
        # root offsets are stored normalised by hip height (same as retargeted mocap)
        root.append([round((a.root[k] + (b.root[k] - a.root[k]) * u) / HIP_H, 5) for k in range(3)])
    contacts = {k: [[int(round(s * fps)), int(round(e * fps))] for s, e in v] for k, v in (cd.contacts or {}).items()}
    squash = [[int(round(t * fps)), s] for t, s in (cd.squash or [])]
    return {"name": cd.name, "fps": fps, "frames": n, "loop": cd.loop, "tags": cd.tags or [cd.name],
            "category": cd.category, "bones": out_bones, "root": root, "root_normalized": True, "contacts": contacts,
            "stride": round(cd.stride / HIP_H, 4) if cd.stride else None,
            "squash": squash, "source": "procedural", "license": "CC0 (generated by StoryForge)"}


def _slerp_ext(a: Q.Q, b: Q.Q, u: float) -> Q.Q:
    """Slerp allowing u outside [0, 1] (overshoot) by scaling the delta rotation."""
    delta = Q.mul(b, Q.conj(a))
    return Q.norm(Q.mul(Q.power(delta, u), a))


# ------------------------------------------------------------------ clip definitions
def _gesture(name, dur, keys, tags=None, bones=UPPER_BONES, squash=None):
    return ClipDef(name, dur, keys, tags or [name], False, bones, None, None, squash, "gesture")


def build_defs() -> dict[str, ClipDef]:
    R = relaxed
    d: dict[str, ClipDef] = {}
    # --- talk gestures (beats while speaking)
    d["talk"] = _gesture("talk", 1.8, [
        Key(0.0, R()),
        Key(0.35, R(arm("R", 55, 30), elbow("R", 70, twist=-50), wrist("R", 10)), ease="out"),
        Key(0.6, R(arm("R", 60, 30), elbow("R", 62, twist=-55), wrist("R", -5)), ease="snap"),
        Key(0.9, R(arm("R", 54, 32), elbow("R", 72, twist=-50), wrist("R", 12))),
        Key(1.25, R(arm("R", 58, 28), elbow("R", 64, twist=-45))),
        Key(1.8, R()),
    ], tags=["talk", "gesture_talk"])
    d["talk_both"] = _gesture("talk_both", 2.0, [
        Key(0.0, R()),
        Key(0.4, R(arm("L", 55, 28), arm("R", 55, 28), elbow("L", 75, twist=-40), elbow("R", 75, twist=-40),
                   spine(4)), ease="out"),
        Key(0.75, R(arm("L", 62, 26), arm("R", 62, 26), elbow("L", 68, twist=-50), elbow("R", 68, twist=-50),
                    spine(2)), ease="snap"),
        Key(1.2, R(arm("L", 52, 32), arm("R", 52, 32), elbow("L", 78, twist=-35), elbow("R", 78, twist=-35), spine(5))),
        Key(2.0, R()),
    ], tags=["talk", "talk_both"])
    d["talk_left"] = _gesture("talk_left", 1.6, [
        Key(0.0, R()),
        Key(0.3, R(arm("L", 56, 26), elbow("L", 70, twist=-45), head(tilt=-4)), ease="out"),
        Key(0.65, R(arm("L", 62, 24), elbow("L", 60, twist=-50), head(tilt=-2)), ease="snap"),
        Key(1.0, R(arm("L", 55, 30), elbow("L", 72, twist=-45))),
        Key(1.6, R()),
    ], tags=["talk", "talk_left"])
    # --- emblematic gestures
    d["wave"] = _gesture("wave", 1.8, [
        Key(0.0, R()),
        Key(0.12, R(arm("R", 78, 0)), ease="out"),  # anticipation dip
        Key(0.35, R(arm("R", -55, 10), elbow("R", 45, twist=-80), head(tilt=6)), ease="back"),
        Key(0.6, R(arm("R", -52, 10), elbow("R", 20, twist=-80), head(tilt=6))),
        Key(0.85, R(arm("R", -55, 10), elbow("R", 50, twist=-80), head(tilt=6))),
        Key(1.1, R(arm("R", -52, 10), elbow("R", 20, twist=-80), head(tilt=6))),
        Key(1.35, R(arm("R", -55, 10), elbow("R", 45, twist=-80), head(tilt=4))),
        Key(1.8, R()),
    ])
    d["point"] = _gesture("point", 1.4, [
        Key(0.0, R()),
        Key(0.15, R(arm("R", 65, -10), elbow("R", 40), spine(twist=6)), ease="out"),  # anticipation pull back
        Key(0.38, R(arm("R", -4, 72), elbow("R", 4), wrist("R", 5), spine(twist=-10), head(turn=-8)), ease="back"),
        Key(1.0, R(arm("R", -2, 70), elbow("R", 6), spine(twist=-9), head(turn=-8))),
        Key(1.4, R()),
    ])
    d["shrug"] = _gesture("shrug", 1.2, [
        Key(0.0, R()),
        Key(0.3, R(shoulder("L", 14), shoulder("R", 14), arm("L", 62, 20), arm("R", 62, 20),
                   elbow("L", 75, twist=-70), elbow("R", 75, twist=-70), head(tilt=8), spine(-2)), ease="back"),
        Key(0.8, R(shoulder("L", 12), shoulder("R", 12), arm("L", 60, 22), arm("R", 60, 22),
                   elbow("L", 72, twist=-70), elbow("R", 72, twist=-70), head(tilt=7))),
        Key(1.2, R()),
    ])
    d["nod"] = _gesture("nod", 0.9, [
        Key(0.0, R()), Key(0.18, R(head(nod=14)), ease="out"), Key(0.36, R(head(nod=-3))),
        Key(0.56, R(head(nod=10)), ease="out"), Key(0.9, R()),
    ], bones=["neck", "head"])
    d["head_shake"] = _gesture("head_shake", 1.1, [
        Key(0.0, R()), Key(0.2, R(head(turn=18))), Key(0.45, R(head(turn=-18))), Key(0.7, R(head(turn=12))),
        Key(1.1, R()),
    ], bones=["neck", "head"])
    d["hands_on_hips"] = _gesture("hands_on_hips", 1.6, [
        Key(0.0, R()),
        Key(0.35, R(arm("L", 48, -22, twist=20), arm("R", 48, -22, twist=20), elbow("L", 105), elbow("R", 105),
                    spine(-4), head(nod=-4)), ease="back"),
        Key(1.3, R(arm("L", 48, -22, twist=20), arm("R", 48, -22, twist=20), elbow("L", 105), elbow("R", 105),
                   spine(-5), head(nod=-5))),
        Key(1.6, R()),
    ], tags=["hands_on_hips", "heroic"])
    d["cross_arms"] = _gesture("cross_arms", 1.8, [
        Key(0.0, R()),
        Key(0.4, R(arm("L", 62, 42), arm("R", 64, 40), elbow("L", 118, twist=10), elbow("R", 112, twist=10),
                   spine(-2), head(nod=-3, tilt=4)), ease="out"),
        Key(1.5, R(arm("L", 62, 42), arm("R", 64, 40), elbow("L", 118, twist=10), elbow("R", 112, twist=10),
                   spine(-2), head(nod=-3, tilt=5))),
        Key(1.8, R()),
    ])
    d["facepalm"] = _gesture("facepalm", 1.6, [
        Key(0.0, R()),
        Key(0.35, R(arm("R", 12, 72), elbow("R", 142, twist=-60), head(nod=16), spine(6)), ease="snap"),
        Key(1.2, R(arm("R", 14, 72), elbow("R", 140, twist=-60), head(nod=18, turn=6), spine(7))),
        Key(1.6, R()),
    ])
    d["cheer"] = _gesture("cheer", 1.6, [
        Key(0.0, R()),
        Key(0.15, R(arm("L", 80, 0), arm("R", 80, 0), spine(6)), (0, 0, -0.03), "out"),
        Key(0.4, R(arm("L", -70, 5), arm("R", -70, 5), elbow("L", 25), elbow("R", 25), spine(-6), head(nod=-10)),
            (0, 0, 0.06), "back"),
        Key(0.7, R(arm("L", -64, 5), arm("R", -64, 5), elbow("L", 35), elbow("R", 35), spine(-4)), (0, 0, 0.0)),
        Key(1.0, R(arm("L", -70, 5), arm("R", -70, 5), elbow("L", 25), elbow("R", 25), spine(-6)), (0, 0, 0.04)),
        Key(1.6, R()),
    ], bones=UPPER_BONES, squash=[(0.15, 0.94), (0.4, 1.06), (0.7, 0.97), (1.0, 1.03), (1.3, 1.0)])
    d["jump"] = ClipDef("jump", 1.3, [
        Key(0.0, R()),
        Key(0.25, merge(R(arm("L", 75, -30), arm("R", 75, -30), spine(14)), both(leg, 38), both(knee, 70),
                        both(ankle, 22)), (0, 0, -0.1), "out"),
        Key(0.42, merge(R(arm("L", -40, 20), arm("R", -40, 20), spine(-6)), both(leg, 8), both(knee, 10),
                        both(ankle, -25)), (0, 0, 0.22), "out"),
        Key(0.62, merge(R(arm("L", -30, 20), arm("R", -30, 20)), both(leg, 30), both(knee, 50)), (0, 0, 0.26), "in"),
        Key(0.8, merge(R(arm("L", 40, 10), arm("R", 40, 10), spine(12)), both(leg, 32), both(knee, 62),
                       both(ankle, 20)), (0, 0, -0.08), "in"),
        Key(1.05, merge(R(spine(3)), both(leg, 6), both(knee, 10)), (0, 0, 0.0), "back"),
        Key(1.3, R()),
    ], ["jump", "big_action"], False, UPPER_BONES + LEG_BONES, {"foot.L": [(0, 0.38), (0.78, 1.3)],
                                                               "foot.R": [(0, 0.38), (0.78, 1.3)]},
        None, [(0.25, 0.9), (0.42, 1.12), (0.62, 1.02), (0.8, 0.86), (1.0, 1.03), (1.15, 1.0)], "action")
    d["gasp"] = _gesture("gasp", 1.0, [
        Key(0.0, R()),
        Key(0.18, R(arm("L", 45, 38), arm("R", 45, 38), elbow("L", 122, twist=-20), elbow("R", 122, twist=-20),
                    spine(-10), head(nod=-8)), (0, 0.04, 0.02), "snap"),
        Key(0.7, R(arm("L", 47, 36), arm("R", 47, 36), elbow("L", 118), elbow("R", 118), spine(-8), head(nod=-6)),
            (0, 0.035, 0.0)),
        Key(1.0, R()),
    ], tags=["gasp", "surprise"], squash=[(0.0, 1.0), (0.18, 1.06), (0.4, 0.99), (0.7, 1.0)])
    d["laugh"] = _gesture("laugh", 1.6, [
        Key(0.0, R()),
        Key(0.2, R(spine(-8), head(nod=-12), arm("L", 66, 20), arm("R", 66, 20), elbow("L", 60), elbow("R", 60)), ease="out"),
        Key(0.45, R(spine(10), head(nod=6), arm("L", 62, 24), arm("R", 62, 24), elbow("L", 70), elbow("R", 70))),
        Key(0.7, R(spine(-5), head(nod=-8), arm("L", 66, 20), arm("R", 66, 20), elbow("L", 62), elbow("R", 62))),
        Key(0.95, R(spine(8), head(nod=4), arm("L", 63, 22), arm("R", 63, 22), elbow("L", 68), elbow("R", 68))),
        Key(1.6, R()),
    ], squash=[(0.2, 1.02), (0.45, 0.97), (0.7, 1.02), (0.95, 0.98), (1.3, 1.0)])
    d["cry"] = _gesture("cry", 2.2, [
        Key(0.0, R()),
        Key(0.4, R(arm("L", 20, 66), arm("R", 20, 66), elbow("L", 150, twist=-40), elbow("R", 150, twist=-40),
                   head(nod=16), spine(10)), ease="out"),
        Key(0.8, R(arm("L", 22, 64), arm("R", 22, 64), elbow("L", 148, twist=-40), elbow("R", 148, twist=-40),
                   head(nod=18), spine(12), shoulder("L", 6), shoulder("R", 6))),
        Key(1.1, R(arm("L", 20, 66), arm("R", 20, 66), elbow("L", 150, twist=-40), elbow("R", 150, twist=-40),
                   head(nod=16), spine(10))),
        Key(1.5, R(arm("L", 22, 64), arm("R", 22, 64), elbow("L", 148, twist=-40), elbow("R", 148, twist=-40),
                   head(nod=18), spine(12), shoulder("L", 6), shoulder("R", 6))),
        Key(2.2, R()),
    ])
    d["think"] = _gesture("think", 2.2, [
        Key(0.0, R()),
        Key(0.45, R(arm("R", 30, 62), elbow("R", 135, twist=-70), arm("L", 62, 35), elbow("L", 95),
                    head(nod=-10, tilt=8, turn=6)), ease="out"),
        Key(1.8, R(arm("R", 31, 61), elbow("R", 133, twist=-70), arm("L", 62, 35), elbow("L", 95),
                   head(nod=-12, tilt=10, turn=8))),
        Key(2.2, R()),
    ])
    d["look_around"] = _gesture("look_around", 2.2, [
        Key(0.0, R()), Key(0.45, R(head(turn=32), spine(twist=8))), Key(1.0, R(head(turn=30), spine(twist=8))),
        Key(1.45, R(head(turn=-30), spine(twist=-8))), Key(1.9, R(head(turn=-28), spine(twist=-7))), Key(2.2, R()),
    ])
    d["thumbs_up"] = _gesture("thumbs_up", 1.4, [
        Key(0.0, R()),
        Key(0.3, R(arm("R", 25, 55), elbow("R", 85, twist=-85), head(tilt=6)), ease="back"),
        Key(1.0, R(arm("R", 24, 56), elbow("R", 82, twist=-85), head(tilt=6))),
        Key(1.4, R()),
    ])
    d["scratch_head"] = _gesture("scratch_head", 1.8, [
        Key(0.0, R()),
        Key(0.35, R(arm("R", -38, 22), elbow("R", 150, twist=-30), head(tilt=-10)), ease="out"),
        Key(0.55, R(arm("R", -34, 22), elbow("R", 142, twist=-30), head(tilt=-10))),
        Key(0.75, R(arm("R", -38, 22), elbow("R", 150, twist=-30), head(tilt=-11))),
        Key(0.95, R(arm("R", -34, 22), elbow("R", 142, twist=-30), head(tilt=-10))),
        Key(1.4, R(arm("R", -36, 22), elbow("R", 148, twist=-30), head(tilt=-9))),
        Key(1.8, R()),
    ])
    d["lean_in"] = _gesture("lean_in", 1.4, [
        Key(0.0, R()), Key(0.4, R(spine(14), head(nod=4)), (0, -0.03, 0), "out"),
        Key(1.1, R(spine(15), head(nod=5)), (0, -0.03, 0)), Key(1.4, R()),
    ])
    d["recoil"] = _gesture("recoil", 1.0, [
        Key(0.0, R()),
        Key(0.15, R(spine(-14), head(nod=-10), arm("L", 40, 40), arm("R", 40, 40), elbow("L", 100), elbow("R", 100)),
            (0, 0.07, 0.01), "snap"),
        Key(0.65, R(spine(-10), head(nod=-6), arm("L", 45, 35), arm("R", 45, 35), elbow("L", 95), elbow("R", 95)),
            (0, 0.06, 0)),
        Key(1.0, R()),
    ], squash=[(0.0, 1.0), (0.15, 1.05), (0.35, 0.98), (0.6, 1.0)])
    d["clap"] = _gesture("clap", 1.4, [
        Key(0.0, R()),
        Key(0.25, R(arm("L", 40, 60), arm("R", 40, 60), elbow("L", 70), elbow("R", 70))),
        Key(0.4, R(arm("L", 40, 72), arm("R", 40, 72), elbow("L", 85), elbow("R", 85))),
        Key(0.55, R(arm("L", 40, 60), arm("R", 40, 60), elbow("L", 70), elbow("R", 70))),
        Key(0.7, R(arm("L", 40, 72), arm("R", 40, 72), elbow("L", 85), elbow("R", 85))),
        Key(0.85, R(arm("L", 40, 60), arm("R", 40, 60), elbow("L", 70), elbow("R", 70))),
        Key(1.0, R(arm("L", 40, 72), arm("R", 40, 72), elbow("L", 85), elbow("R", 85))),
        Key(1.4, R()),
    ])
    shiver_a = R(arm("L", 60, 45), arm("R", 60, 45), elbow("L", 120), elbow("R", 120), shoulder("L", 10),
                 shoulder("R", 10), spine(6))
    shiver_b = R(arm("L", 61, 44), arm("R", 59, 46), elbow("L", 122), elbow("R", 118), shoulder("L", 12),
                 shoulder("R", 8), spine(6, side=2))
    d["shiver"] = _gesture("shiver", 1.6, [Key(0.0, R()), Key(0.3, shiver_a, ease="out")] +
                           [Key(0.3 + 0.08 * i, shiver_b if i % 2 else shiver_a, ease="linear") for i in range(1, 13)] +
                           [Key(1.6, R())])
    d["bow"] = _gesture("bow", 1.6, [
        Key(0.0, R()), Key(0.5, R(spine(32), head(nod=10)), ease="smooth"), Key(0.9, R(spine(32), head(nod=10))),
        Key(1.6, R()),
    ])
    d["pick_up"] = ClipDef("pick_up", 1.6, [
        Key(0.0, R()),
        Key(0.5, merge(R(spine(34), head(nod=12), arm("R", 62, 48), elbow("R", 20)), both(leg, 22), both(knee, 36),
                       both(ankle, 12)), (0, 0, -0.07), "smooth"),
        Key(0.75, merge(R(spine(32), head(nod=10), arm("R", 64, 46), elbow("R", 30)), both(leg, 22), both(knee, 36),
                        both(ankle, 12)), (0, 0, -0.07)),
        Key(1.2, R(arm("R", 52, 38), elbow("R", 75), head(nod=6)), (0, 0, 0), "smooth"),
        Key(1.6, R(arm("R", 55, 35), elbow("R", 72))),
    ], ["pick_up", "reach"], False, UPPER_BONES + LEG_BONES, {"foot.L": [(0, 1.6)], "foot.R": [(0, 1.6)]},
        None, None, "action")
    d["give"] = _gesture("give", 1.4, [
        Key(0.0, R()),
        Key(0.4, R(arm("R", 18, 78), elbow("R", 18, twist=-60), spine(6)), ease="out"),
        Key(1.0, R(arm("R", 16, 80), elbow("R", 16, twist=-60), spine(6))),
        Key(1.4, R()),
    ])
    d["peek"] = _gesture("peek", 1.4, [
        Key(0.0, R()), Key(0.35, R(spine(4, side=14), head(tilt=12, turn=-6)), ease="out"),
        Key(1.1, R(spine(4, side=15), head(tilt=13, turn=-8))), Key(1.4, R()),
    ])
    d["hold_item"] = _gesture("hold_item", 1.0, [
        Key(0.0, R(arm("R", 55, 34), elbow("R", 78, twist=-40))), Key(1.0, R(arm("R", 55, 34), elbow("R", 78, twist=-40))),
    ], tags=["hold_item"], bones=["upper_arm.R", "forearm.R", "hand.R"])
    d["show_item"] = _gesture("show_item", 1.4, [
        Key(0.0, R(arm("R", 55, 34), elbow("R", 78, twist=-40))),
        Key(0.4, R(arm("R", 5, 70), elbow("R", 30, twist=-70), head(tilt=5)), ease="back"),
        Key(1.0, R(arm("R", 6, 70), elbow("R", 32, twist=-70), head(tilt=5))),
        Key(1.4, R(arm("R", 55, 34), elbow("R", 78, twist=-40))),
    ], tags=["show_item"])
    # --- locomotion (in place; root motion comes from blocking paths)
    d["walk"] = _cycle("walk", 1.0, 26, 48, 22, 0.022, 0.5, ["walk", "locomotion"])
    d["run"] = _cycle("run", 0.62, 40, 85, 45, 0.05, 1.05, ["run", "locomotion"], lean=10)
    d["tiptoe"] = _cycle("tiptoe", 1.4, 22, 62, 18, 0.015, 0.36, ["tiptoe", "sneak", "locomotion"], lean=12,
                         arms_up=True)
    # --- idle base layer (6 s loop: 3 s breathing x 2, one weight shift)
    d["idle"] = _idle()
    return d


def _cycle(name, period, thigh, knee_bend, arm_swing, bob, stride, tags, lean=3, arms_up=False) -> ClipDef:
    keys = []
    steps = 8
    for i in range(steps + 1):
        ph = i / steps
        a = math.sin(2 * math.pi * ph)
        b = math.sin(2 * math.pi * ph + math.pi)
        # knee bends during swing (when the thigh moves forward)
        kl = knee_bend * max(0.0, math.sin(2 * math.pi * ph + 0.9)) + 6
        kr = knee_bend * max(0.0, math.sin(2 * math.pi * ph + math.pi + 0.9)) + 6
        al = 10 * math.sin(2 * math.pi * ph - 0.6)
        ar = 10 * math.sin(2 * math.pi * ph + math.pi - 0.6)
        if arms_up:
            arms = merge(arm("L", 35, 10 + 8 * b), arm("R", 35, 10 + 8 * a), elbow("L", 90), elbow("R", 90))
        else:
            arms = merge(arm("L", 70, 8 + arm_swing * b), arm("R", 70, 8 + arm_swing * a), elbow("L", 18 + 10 * max(0, b)),
                         elbow("R", 18 + 10 * max(0, a)))
        pose = merge(relaxed(arms), leg("L", thigh * a), leg("R", thigh * b), knee("L", kl), knee("R", kr),
                     ankle("L", al), ankle("R", ar), spine(lean, twist=6 * a), head(nod=-lean * 0.6, turn=-3 * a))
        z = bob * abs(math.cos(2 * math.pi * ph))
        keys.append(Key(ph * period, pose, (0.0, 0.0, z - bob * 0.5), "linear"))
    contacts = {"foot.L": [(0.5 * period, 0.95 * period)], "foot.R": [(0.0, 0.45 * period)]}
    return ClipDef(name, period, keys, tags, True, UPPER_BONES + LEG_BONES, contacts, stride, None, "locomotion")


def _idle() -> ClipDef:
    keys = []
    period = 6.0
    for i in range(13):
        t = i * period / 12
        br = math.sin(2 * math.pi * t / 3.0)        # breathing 3 s
        ws = math.sin(2 * math.pi * t / period)     # weight shift 6 s
        pose = relaxed(spine(fwd=-0.8 * br, side=1.6 * ws), head(nod=0.6 * br, tilt=-1.2 * ws, turn=1.5 * math.sin(2 * math.pi * t / 4.0)),
                       shoulder("L", 1.5 + 1.2 * br), shoulder("R", 1.5 + 1.2 * br),
                       arm("L", 72 + 1.0 * br, 8), arm("R", 72 + 1.0 * br, 8),
                       leg("L", 2 * max(0, -ws), abduct=1.5 * ws), leg("R", 2 * max(0, ws), abduct=-1.5 * ws),
                       knee("L", 4 + 5 * max(0, -ws)), knee("R", 4 + 5 * max(0, ws)))
        keys.append(Key(t, pose, (0.012 * ws, 0.0, -0.004 * abs(ws) + 0.003 * br), "smooth"))
    return ClipDef("idle", period, keys, ["idle", "base"], True, UPPER_BONES + LEG_BONES,
                   {"foot.L": [(0, period)], "foot.R": [(0, period)]}, None, None, "idle")


_CACHE: dict[int, dict[str, dict]] = {}


def builtin_clips(fps: int = FPS) -> dict[str, dict]:
    if fps not in _CACHE:
        _CACHE[fps] = {name: sample(cd, fps) for name, cd in build_defs().items()}
    return _CACHE[fps]


GESTURE_FALLBACK = {
    "wave": "wave", "point": "point", "shrug": "shrug", "nod": "nod", "head_shake": "head_shake",
    "hands_on_hips": "hands_on_hips", "cross_arms": "cross_arms", "facepalm": "facepalm", "cheer": "cheer",
    "jump": "jump", "gasp": "gasp", "laugh": "laugh", "cry": "cry", "think": "think", "look_around": "look_around",
    "thumbs_up": "thumbs_up", "scratch_head": "scratch_head", "lean_in": "lean_in", "recoil": "recoil", "clap": "clap",
    "shiver": "shiver", "bow": "bow", "pick_up": "pick_up", "give": "give", "peek": "peek", "talk": "talk",
}
