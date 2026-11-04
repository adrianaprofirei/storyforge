"""Clip actions + NLA layering + post passes (foot locking, collision fixes, secondary motion).

Track stack per character (bottom -> top): base (idle), locomotion, hold, gesture, correction,
secondary. Gesture actions only contain the bones a gesture moves, so lower layers keep driving the
rest of the body. Strips blend in/out over a few frames for smooth transitions.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Quaternion, Vector

from storyforge_blender import compat

TRACK_ORDER = ["base", "locomotion", "hold", "gesture", "correction", "secondary"]


def _q(v) -> Quaternion:
    return Quaternion((v[0], v[1], v[2], v[3]))


def _scale_delta(q: Quaternion, ref: Quaternion, k: float) -> Quaternion:
    """Exaggerate/damp the rotation relative to `ref` (power of the delta quaternion)."""
    if abs(k - 1.0) < 1e-3:
        return q
    delta = q @ ref.inverted()
    axis, ang = delta.to_axis_angle()
    return Quaternion(axis, ang * k) @ ref


def build_clip_action(rig, clip: dict, name: str, amplitude: float = 1.0, bones: list[str] | None = None,
                      hip_height: float = 0.43, relaxed: dict | None = None):
    """Canonical clip -> Blender action (local quaternions per frame), assigned temporarily."""
    act = bpy.data.actions.new(name)
    adt = rig.animation_data or rig.animation_data_create()
    prev = adt.action
    adt.action = act
    n = clip["frames"]
    loop = bool(clip.get("loop"))
    use_bones = [b for b in (bones or clip["bones"].keys()) if b in clip["bones"] and b in rig.pose.bones]
    for b in use_bones:
        pb = rig.pose.bones[b]
        rest = pb.bone.matrix_local.to_quaternion()
        rest_inv = rest.inverted()
        seq = clip["bones"][b]
        ref = _q(relaxed[b]) if relaxed and b in relaxed else _q(seq[0])
        keys = [[], [], [], []]
        last = None
        frames = list(range(n)) + ([n] if loop else [])
        for i in frames:
            L = _q(seq[i % n] if loop else seq[min(i, len(seq) - 1)])
            L = _scale_delta(L, ref, amplitude)
            basis = rest_inv @ L @ rest
            if last is not None and basis.dot(last) < 0:
                basis.negate()
            last = basis
            for c in range(4):
                keys[c].append((float(i), basis[c]))
        dp = f'pose.bones["{b}"].rotation_quaternion'
        for c in range(4):
            compat.set_keys(rig, dp, c, keys[c], "LINEAR", group=b)
    root = clip.get("root")
    if root and "hips" in rig.pose.bones and (bones is None or "hips" in use_bones or clip.get("category") != "gesture"):
        pb = rig.pose.bones["hips"]
        r3 = pb.bone.matrix_local.to_3x3().inverted()
        scale = hip_height if clip.get("root_normalized", True) else 1.0
        if clip.get("category") in ("locomotion", "idle"):
            # in place: remove horizontal travel (root motion comes from the blocking path)
            x0, y0 = root[0][0], root[0][1]
            x1, y1 = root[-1][0], root[-1][1]
        else:
            x0 = y0 = x1 = y1 = 0.0
        keys = [[], [], []]
        frames = list(range(n)) + ([n] if loop else [])
        for i in frames:
            r = root[i % n] if loop else root[min(i, len(root) - 1)]
            u = (i / max(1, n - 1)) if not loop else 0.0
            w = Vector(((r[0] - (x0 + (x1 - x0) * u)) * scale, (r[1] - (y0 + (y1 - y0) * u)) * scale, r[2] * scale))
            if clip.get("category") == "gesture":
                w *= min(1.3, amplitude)
            loc = r3 @ w
            for c in range(3):
                keys[c].append((float(i), loc[c]))
        for c in range(3):
            compat.set_keys(rig, 'pose.bones["hips"].location', c, keys[c], "LINEAR", group="hips")
    adt.action = prev
    act.use_fake_user = False
    return act


def _track(rig, name: str):
    adt = rig.animation_data or rig.animation_data_create()
    existing = [t for t in adt.nla_tracks if t.name == name or t.name.startswith(name + ".")]
    return existing


def add_strip(rig, track: str, action, start: float, scale: float = 1.0, repeat: float = 1.0, blend_in: float = 0,
              blend_out: float = 0, extrapolation: str = "NOTHING", blend_type: str = "REPLACE", influence=None):
    adt = rig.animation_data or rig.animation_data_create()
    candidates = _track(rig, track)
    last_err = None
    for attempt in range(6):
        tname = track if attempt == 0 else f"{track}.{attempt:03d}"
        tr = next((t for t in candidates if t.name == tname), None)
        if tr is None:
            tr = adt.nla_tracks.new()
            tr.name = tname
            candidates.append(tr)
        try:
            strip = tr.strips.new(action.name, int(math.floor(start)), action)
        except RuntimeError as exc:  # overlaps an existing strip on this track
            last_err = exc
            continue
        if hasattr(strip, "action_slot") and getattr(strip, "action_slot", None) is None and hasattr(action, "slots"):
            slots = list(action.slots)
            if slots:
                try:
                    strip.action_slot = slots[0]
                except Exception:
                    pass
        strip.use_auto_blend = False
        strip.blend_type = blend_type
        strip.extrapolation = extrapolation
        strip.scale = max(0.05, scale)
        strip.repeat = max(0.05, repeat)
        strip.frame_start = float(start)
        length = strip.frame_end - strip.frame_start
        strip.blend_in = min(blend_in, length * 0.45)
        strip.blend_out = min(blend_out, length * 0.45)
        if influence is not None:
            strip.use_animated_influence = True
            strip.influence = influence
        return strip
    raise RuntimeError(f"could not place strip on {track}: {last_err}")


def order_tracks(rig):
    """NLA evaluates bottom (index 0) to top; rebuild order to TRACK_ORDER via track moves isn't
    exposed in the API, so tracks are created in order by the caller (see apply_performance)."""
    return [t.name for t in rig.animation_data.nla_tracks] if rig.animation_data else []


def apply_strips(rig, plan: dict, clips: dict, relaxed: dict, char_id: str):
    hip_h = float(plan.get("hip_height", 0.43))
    adt = rig.animation_data or rig.animation_data_create()
    adt.action = None
    # create tracks bottom->top in the canonical order so the stacking is right
    for name in TRACK_ORDER[:4]:
        if not any(t.name == name for t in adt.nla_tracks):
            t = adt.nla_tracks.new()
            t.name = name
    cache: dict = {}
    for s in sorted(plan.get("strips", []), key=lambda s: (TRACK_ORDER.index(s["track"]), s["start"])):
        clip = clips.get(s["clip"])
        if clip is None:
            continue
        key = (s["clip"], round(s.get("amplitude", 1.0), 2), tuple(s.get("bones") or ()))
        act = cache.get(key)
        if act is None:
            act = build_clip_action(rig, clip, f"{char_id}_{s['clip']}_{len(cache)}", s.get("amplitude", 1.0),
                                    s.get("bones"), hip_h, relaxed)
            cache[key] = act
        add_strip(rig, s["track"], act, s["start"], s.get("scale", 1.0), s.get("repeat", 1.0), s.get("blend_in", 0),
                  s.get("blend_out", 0), s.get("extrapolation", "NOTHING"))


# --------------------------------------------------------------------------- post passes
def _world_bone_head(rig, name):
    return rig.matrix_world @ rig.pose.bones[name].head


def _world_bone_tail(rig, name):
    return rig.matrix_world @ rig.pose.bones[name].tail


def setup_leg_ik(rig):
    cons = {}
    for side in ("L", "R"):
        pb = rig.pose.bones.get(f"shin.{side}")
        if pb is None or f"ik_foot.{side}" not in rig.pose.bones:
            continue
        c = pb.constraints.new("IK")
        c.name = "IK"
        c.target = rig
        c.subtarget = f"ik_foot.{side}"
        c.pole_target = rig
        c.pole_subtarget = f"pole_knee.{side}"
        c.pole_angle = math.radians(-90)
        c.chain_count = 2
        c.use_tail = True
        c.use_stretch = False
        c.influence = 0.0
        cons[side] = c
    return cons


def _calibrate_pole(scene, rig, cons, frame):
    """Pick the pole angle that keeps the knee pointing forward (rig-roll independent)."""
    for side, c in cons.items():
        best, best_score = c.pole_angle, -1e9
        c.influence = 1.0
        ik = rig.pose.bones[f"ik_foot.{side}"]
        # raise the target 6 cm (armature space) so the leg bends and the knee direction is defined
        ik.location = ik.bone.matrix_local.to_3x3().inverted() @ Vector((0, 0, 0.06))
        for deg in (-90, 0, 90, 180):
            c.pole_angle = math.radians(deg)
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            knee = rig.matrix_world.inverted() @ _world_bone_head(rig, f"shin.{side}")
            score = -knee.y  # forward = -Y
            if score > best_score:
                best, best_score = c.pole_angle, score
        c.pole_angle = best
        c.influence = 0.0
        ik.location = (0, 0, 0)


def foot_lock(scene, rig, metrics: dict, frame_start: int, frame_end: int, fps: int, log=print):
    """Lock planted feet with 2-bone IK (no foot sliding while standing, turning or walking)."""
    cons = setup_leg_ik(rig)
    if not cons:
        return {}
    _calibrate_pole(scene, rig, cons, frame_start)
    ankle_rest = metrics["ankle_z"]
    pos = {s: [] for s in cons}
    for f in range(frame_start, frame_end + 1):
        scene.frame_set(f)
        for s in cons:
            pos[s].append(_world_bone_tail(rig, f"shin.{s}").copy())
    inv_cache = []
    for f in range(frame_start, frame_end + 1):
        scene.frame_set(f)
        inv_cache.append(rig.matrix_world.inverted().copy())
    stats = {}
    for s in cons:
        ps = pos[s]
        n = len(ps)
        contact = []
        for i in range(n):
            h = ps[i].z - ankle_rest
            v = (ps[min(n - 1, i + 1)] - ps[max(0, i - 1)]).length * fps / 2
            contact.append(h < 0.03 and v < 0.45)
        # intervals
        spans, start = [], None
        for i, on in enumerate(contact + [False]):
            if on and start is None:
                start = i
            elif not on and start is not None:
                if i - start >= 3:
                    spans.append((start, i - 1))
                start = None
        pb = rig.pose.bones[f"ik_foot.{s}"]
        rest_head = pb.bone.head_local
        r3_inv = pb.bone.matrix_local.to_3x3().inverted()
        lk = [[], [], []]
        infl = [(float(frame_start - 1), 0.0)]
        slide = 0.0
        for a, b in spans:
            lock = ps[a].copy()
            lock.z = ankle_rest
            slide = max(slide, max((ps[i] - ps[a]).xy.length for i in range(a, b + 1)))
            for i in range(a, b + 1):
                arm_target = inv_cache[i] @ lock
                local = r3_inv @ (arm_target - rest_head)
                for k in range(3):
                    lk[k].append((float(frame_start + i), local[k]))
            ramp = 2
            infl += [(float(frame_start + a - ramp), 0.0), (float(frame_start + a), 1.0),
                     (float(frame_start + b), 1.0), (float(frame_start + b + ramp), 0.0)]
        if lk[0]:
            for k in range(3):
                compat.set_keys(rig, f'pose.bones["ik_foot.{s}"].location', k, lk[k], "LINEAR", group=f"ik_foot.{s}")
        infl.sort()
        dedup = {}
        for f, v in infl:
            dedup[f] = max(v, dedup.get(f, 0.0))
        compat.set_keys(rig, f'pose.bones["shin.{s}"].constraints["IK"].influence', 0, sorted(dedup.items()), "LINEAR")
        stats[s] = {"contacts": len(spans), "max_fk_slide_m": round(slide, 4)}
    return stats


def collision_fix(scene, rig, metrics: dict, frame_start: int, frame_end: int, relaxed_ref=None, step: int = 2):
    """Push hands out of the torso: upper-arm abduction on a COMBINE correction layer."""
    tw, td = metrics["torso_w"], metrics["torso_d"]
    limb = metrics["limb"]
    x_in = tw / 2 + limb * 0.45
    y_in = td / 2 + limb * 0.45
    z0, z1 = metrics["hip_z"] - 0.02, metrics["neck_base"]
    corr = {"L": [], "R": []}
    hits = 0
    for f in range(frame_start, frame_end + 1, step):
        scene.frame_set(f)
        inv = rig.matrix_world.inverted()
        for side in ("L", "R"):
            p = inv @ _world_bone_tail(rig, f"hand.{side}")
            inside = abs(p.x) < x_in and abs(p.y) < y_in and z0 < p.z < z1
            ang = 0.0
            if inside:
                depth = x_in - abs(p.x)
                ang = min(30.0, math.degrees(depth / max(0.05, metrics["arm_len"])) * 1.3 + 4.0)
                hits += 1
            corr[side].append((f, ang))
    if hits == 0:
        return 0
    act = bpy.data.actions.new(f"{rig.name}_corrections")
    adt = rig.animation_data
    prev = adt.action
    adt.action = act
    for side, sg in (("L", 1), ("R", -1)):
        pb = rig.pose.bones[f"upper_arm.{side}"]
        rest = pb.bone.matrix_local.to_quaternion()
        keys = [[], [], [], []]
        # smooth the correction curve (no pops)
        vals = [a for _, a in corr[side]]
        sm = [max(vals[max(0, i - 2):i + 3]) for i in range(len(vals))]
        for (f, _), a in zip(corr[side], sm, strict=False):
            q = rest.inverted() @ Quaternion((0, 1, 0), math.radians(-sg * a)) @ rest
            for c in range(4):
                keys[c].append((float(f), q[c]))
        for c in range(4):
            compat.set_keys(rig, f'pose.bones["upper_arm.{side}"].rotation_quaternion', c, keys[c], "BEZIER",
                            group=f"upper_arm.{side}")
    adt.action = prev
    add_strip(rig, "correction", act, act.frame_range[0], blend_type="COMBINE", extrapolation="NOTHING")
    return hits


def secondary_motion(scene, rig, frame_start: int, frame_end: int, fps: int, bones=("hair_1", "backpack"),
                     stiffness: float = 90.0, damping: float = 9.0, gain: float = 0.006):
    """Damped-spring lag for hair and accessories, baked to a top NLA layer."""
    present = [b for b in bones if b in rig.pose.bones]
    if not present:
        return 0
    dt = 1.0 / fps
    tips = {b: [] for b in present}
    mats = {b: [] for b in present}
    for f in range(frame_start, frame_end + 1):
        scene.frame_set(f)
        for b in present:
            pb = rig.pose.bones[b]
            m = rig.matrix_world @ pb.matrix
            mats[b].append(m.to_3x3().copy())
            tips[b].append((rig.matrix_world @ pb.tail).copy())
    act = bpy.data.actions.new(f"{rig.name}_secondary")
    adt = rig.animation_data
    prev = adt.action
    adt.action = act
    for b in present:
        pb = rig.pose.bones[b]
        ts = tips[b]
        th = Vector((0, 0))
        om = Vector((0, 0))
        keys = [[], [], [], []]
        child_keys = [[], [], [], []]
        child = "hair_2" if b == "hair_1" and "hair_2" in rig.pose.bones else None
        for i in range(len(ts)):
            if 0 < i < len(ts) - 1:
                acc = (ts[i + 1] - 2 * ts[i] + ts[i - 1]) / (dt * dt)
            else:
                acc = Vector((0, 0, 0))
            local_acc = mats[b][i].inverted() @ acc  # in bone space: x, z perpendicular to the bone
            drive = Vector((-local_acc.z, local_acc.x)) * gain
            alpha = -stiffness * th - damping * om - drive * stiffness
            om += alpha * dt
            th += om * dt
            th.x = max(-0.6, min(0.6, th.x))
            th.y = max(-0.6, min(0.6, th.y))
            q = Quaternion((1, 0, 0), th.x) @ Quaternion((0, 0, 1), th.y)
            for c in range(4):
                keys[c].append((float(frame_start + i), q[c]))
            if child:
                q2 = Quaternion((1, 0, 0), th.x * 0.6) @ Quaternion((0, 0, 1), th.y * 0.6)
                for c in range(4):
                    child_keys[c].append((float(frame_start + i), q2[c]))
        for c in range(4):
            compat.set_keys(rig, f'pose.bones["{b}"].rotation_quaternion', c, keys[c], "LINEAR", group=b)
            if child:
                compat.set_keys(rig, f'pose.bones["{child}"].rotation_quaternion', c, child_keys[c], "LINEAR", group=child)
        del pb
    adt.action = prev
    add_strip(rig, "secondary", act, act.frame_range[0], blend_type="COMBINE", extrapolation="NOTHING")
    return len(present)


def apply_squash(rig, keys: list):
    """Squash & stretch on the character object (pivot at the feet), volume preserving."""
    if not keys:
        return
    sz = [(k[0], k[1]) for k in keys]
    sxy = [(k[0], 1.0 / math.sqrt(max(0.5, k[1]))) for k in keys]
    compat.set_keys(rig, "scale", 2, sz, "BEZIER")
    compat.set_keys(rig, "scale", 0, sxy, "BEZIER")
    compat.set_keys(rig, "scale", 1, sxy, "BEZIER")
