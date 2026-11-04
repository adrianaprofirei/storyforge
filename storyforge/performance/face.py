"""Facial performance planning: expressions, blinks, gaze/eyelines, listener reactions, emotion FX.

Everything is computed as dense per-frame curves (numpy), combined channel by channel, then
simplified (Ramer-Douglas-Peucker) into keyframes for the scene spec:

* expressions  speaker = beat emotion x intensity (derived emotions are blends of the 9 base
               expressions); listeners = reaction expression; silent beats spread to everyone.
               Transitions ease over ~6 frames with a small overshoot on strong emotions.
* blinks       gamma-distributed intervals (mean ~3.6 s, clamped 2-6 s), plus blinks on head
               turns, on cuts (the character on screen right after a cut) and on emotional beats;
               slower blinks when sad/tired; occasional double blinks. lid = max(expression, blink).
* gaze         listeners look at the speaker, the speaker at the addressee with look-aways while
               thinking; small saccades every 0.4-1.4 s; on big target changes the eyes lead and
               the head follows over ~10 frames, then the eyes re-centre (head look layer).
* reactions    listeners react to lines from their emotion (smile + nod, gasp, sympathy, eye-roll,
               confusion) 0.25-0.5 s after the line starts; body reactions become gesture strips.
* FX           sweat drop, tears, anger mark, blush, sparkles, question mark, shock lines, ! and
               lightbulb from the screenplay plus automatic ones from strong emotions.
"""

from __future__ import annotations

import math
import random

import numpy as np

from storyforge.models.constants import BASE_EXPRESSIONS, DERIVED_EMOTIONS
from storyforge.performance.lipsync import openness_curve
from storyforge.staging import head_point, position_at

FRAME_START = 1

EXPRESSIONS: dict[str, dict[str, float]] = {
    "neutral": {},
    "happy": {"smile": 0.85, "lid_bottom": 0.3, "brow_up": 0.25},
    "sad": {"frown": 0.7, "brow_sad": 1.0, "lid_top": 0.3, "lid_tilt": -0.6, "gaze_down": 0.25},
    "angry": {"frown": 0.45, "tight": 0.5, "brow_angry": 1.0, "lid_top": 0.22, "lid_tilt": 0.8},
    "shocked": {"open_shock": 0.85, "brow_up": 1.0, "pupil_small": 0.3},
    "smug": {"smirk_R": 0.85, "lid_top": 0.42, "brow_skeptic_L": 0.7, "lid_tilt": 0.15},
    "scared": {"wavy": 0.7, "frown": 0.3, "brow_sad": 0.7, "brow_up": 0.6, "pupil_small": 0.3},
    "confused": {"smirk_L": 0.35, "frown": 0.15, "brow_skeptic_R": 0.9, "lid_tilt": 0.1},
    "embarrassed": {"wavy": 0.45, "smile": 0.3, "brow_sad": 0.5, "lid_top": 0.25, "blush": 1.0, "gaze_down": 0.3},
}
MOUTH_KEYS = ["smile", "frown", "smirk_L", "smirk_R", "open_shock", "tight", "wavy"]
BROW_KEYS = ["brow_up", "brow_down", "brow_angry", "brow_sad", "brow_skeptic_L", "brow_skeptic_R"]
SPEECH_DAMP = {"open_shock": 0.35, "wavy": 0.5, "tight": 0.6}  # visemes carry the mouth while speaking

REACTIONS = {  # line emotion -> (listener expression, intensity scale, body gesture or None)
    "happy": ("happy", 0.6, "nod"), "excited": ("happy", 0.7, None), "sad": ("sad", 0.55, None),
    "angry": ("scared", 0.45, "recoil"), "shocked": ("shocked", 0.7, "gasp"), "scared": ("scared", 0.5, None),
    "smug": ("smug", 0.5, None), "confused": ("confused", 0.5, None), "embarrassed": ("happy", 0.45, None),
    "determined": ("happy", 0.35, "nod"), "neutral": ("neutral", 0.0, None), "tired": ("sad", 0.3, None),
    "relieved": ("happy", 0.5, None), "suspicious": ("confused", 0.45, None),
}
AUTO_FX = [("embarrassed", 0.5, "blush"), ("angry", 0.8, "anger_mark"), ("shocked", 0.92, "shock_lines"),
           ("confused", 0.65, "question_mark"), ("scared", 0.8, "sweat_drop"), ("sad", 0.85, "tears")]
EYE_RANGE_YAW, EYE_RANGE_PITCH = 28.0, 18.0


def expression_weights(emotion: str, intensity: float) -> dict[str, float]:
    if emotion in DERIVED_EMOTIONS:
        out: dict[str, float] = {}
        for base, w in DERIVED_EMOTIONS[emotion].items():
            for k, v in EXPRESSIONS[base].items():
                out[k] = out.get(k, 0.0) + v * w * intensity
        return out
    base = emotion if emotion in BASE_EXPRESSIONS else "neutral"
    return {k: v * intensity for k, v in EXPRESSIONS[base].items()}


# ------------------------------------------------------------------ curve helpers
def rdp(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        x0, y0 = points[a]
        x1, y1 = points[b]
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            x, y = points[i]
            t = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
            d = abs(y - (y0 + (y1 - y0) * t))
            if d > best:
                best, idx = d, i
        if best > eps and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep, strict=False) if k]


def to_keys(curve: np.ndarray, eps: float = 0.008, offset: int = FRAME_START) -> list[list[float]]:
    pts = [(float(i + offset), float(v)) for i, v in enumerate(curve)]
    simple = rdp(pts, eps)
    return [[round(f, 2), round(v, 4)] for f, v in simple]


def ease_track(segments: list[tuple[int, int, float]], n: int, ramp: int = 6, overshoot: float = 0.0) -> np.ndarray:
    """Piecewise target values [(f0, f1, value)] -> smooth curve with eased ramps."""
    target = np.zeros(n, dtype=np.float32)
    for f0, f1, v in segments:
        target[max(0, f0):max(0, min(n, f1))] = v
    if ramp <= 1:
        return target
    # critically damped follow (smooth, no ringing) with optional overshoot on rises
    out = np.zeros(n, dtype=np.float32)
    x, vel = float(target[0]), 0.0
    k = (2.0 * math.pi / (ramp * 2.2)) ** 2
    c = 2.0 * math.sqrt(k) * (1.0 - overshoot)
    for i in range(n):
        acc = k * (target[i] - x) - c * vel
        vel += acc
        x += vel
        out[i] = x
    return out


# ------------------------------------------------------------------ main planner
def plan_faces(timeline: dict, blocking: dict, cast: dict, fps: int, shotlist: dict | None = None,
               seed: int = 99) -> tuple[dict, list[dict]]:
    n = max(2, timeline["frames"])
    cast_ids = timeline["cast"]
    beats = timeline["beats"]
    faces: dict[str, dict] = {}
    fx_events: list[dict] = []
    shots = (shotlist or {}).get("shots", [])
    for ci, cid in enumerate(cast_ids):
        rng = random.Random(seed + 101 * ci)
        settings = (cast.get(cid) or {}).get("settings", {}) or {}
        # ---------------- expressions (segments of target weights)
        segs: dict[str, list[tuple[int, int, float]]] = {}
        speaking = np.zeros(n, dtype=bool)
        mood = np.zeros(n, dtype=np.float32)  # sadness/tiredness drives slower blinks

        def add(ch, f0, f1, v, _segs=segs):
            _segs.setdefault(ch, []).append((f0, f1, v))

        for bi, b in enumerate(beats):
            f0 = int(round(b["start"] * fps))
            nb = beats[bi + 1] if bi + 1 < len(beats) else None
            f1 = int(round((nb["start"] if nb else timeline["duration"]) * fps))
            emo, inten = b.get("emotion", "neutral"), float(b.get("intensity", 0.5))
            if b.get("speaker") == cid:
                w = expression_weights(emo, inten)
                if b.get("audio"):
                    a0, a1 = int(b["audio"]["start"] * fps), int(b["audio"]["end"] * fps)
                    speaking[max(0, a0):min(n, a1)] = True
            elif not b.get("speaker"):
                actor = b.get("actor")
                w = expression_weights(emo, inten * (1.0 if actor == cid else 0.65))
            else:
                rexpr, rscale, _ = REACTIONS.get(emo, ("neutral", 0.0, None))
                # a listener who is addressed reacts more
                if b.get("addressee") == cid:
                    rscale *= 1.2
                w = expression_weights(rexpr, min(1.0, inten * rscale))
                f0 = f0 + int(fps * rng.uniform(0.25, 0.5))
            if emo in ("sad", "tired"):
                mood[max(0, f0):min(n, f1)] = inten
            for ch, v in w.items():
                add(ch, f0, f1, v)
            # emotion FX: scripted + automatic from strong emotions
            if b.get("speaker") == cid or b.get("actor") == cid:
                for fx in b.get("fx") or []:
                    if fx.get("character") == cid:
                        fx_events.append(_fx(cid, fx["type"], b, fps, inten))
                scripted = [x for x in b.get("fx") or [] if x.get("character") == cid]
                for e, thr, kind in AUTO_FX:
                    if emo == e and inten >= thr and not scripted:
                        fx_events.append(_fx(cid, kind, b, fps, inten))
            elif b.get("speaker") is None:
                for fx in b.get("fx") or []:
                    if fx.get("character") == cid:
                        fx_events.append(_fx(cid, fx["type"], b, fps, inten))
        curves: dict[str, np.ndarray] = {}
        for ch, sg in segs.items():
            strong = max(v for _, _, v in sg) if sg else 0.0
            curves[ch] = ease_track(sg, n, ramp=6, overshoot=0.15 if strong > 0.7 else 0.0)
        for ch, damp in SPEECH_DAMP.items():
            if ch in curves:
                curves[ch] = np.where(speaking, curves[ch] * damp, curves[ch])
        # ---------------- gaze + head look
        gaze_x, gaze_y, look_yaw, look_pitch, turns = plan_gaze(cid, timeline, blocking, fps, n, rng)
        if "gaze_down" in curves:
            gaze_y = gaze_y - curves["gaze_down"] * 0.8
        # ---------------- blinks
        cuts = [int(round(s["start"] * fps)) for s in shots if s.get("subject") == cid or s.get("partner") == cid]
        emo_frames = [int(round(b["start"] * fps)) for b in beats if float(b.get("intensity", 0)) >= 0.75 and
                      (b.get("speaker") == cid or not b.get("speaker"))]
        blink_curve, blinks = plan_blinks(n, fps, rng, mood, turns, cuts, emo_frames,
                                          rate=float(settings.get("blink_rate", 1.0)))
        lid_expr = np.clip(curves.get("lid_top", np.zeros(n)), 0.0, 0.85)
        lid_top = np.maximum(lid_expr, blink_curve)
        eyes = {
            "lid_top": to_keys(lid_top, 0.01),
            "lid_bottom": to_keys(np.clip(curves.get("lid_bottom", np.zeros(n)), 0, 0.8)),
            "lid_tilt": to_keys(np.clip(curves.get("lid_tilt", np.zeros(n)), -1, 1)),
            "pupil_scale": to_keys(1.0 - np.clip(curves.get("pupil_small", np.zeros(n)), 0, 0.45)),
            "gaze_x": to_keys(np.clip(gaze_x, -1, 1), 0.01),
            "gaze_y": to_keys(np.clip(gaze_y, -1, 1), 0.01),
        }
        faces[cid] = {
            "mouth_expr": {k: to_keys(np.clip(curves[k], 0, 1.2)) for k in MOUTH_KEYS if k in curves},
            "brows": {k: to_keys(np.clip(curves[k], 0, 1.2)) for k in BROW_KEYS if k in curves},
            "eyes": eyes,
            "blush": to_keys(np.clip(curves.get("blush", np.zeros(n)), 0, 1)) if "blush" in curves else [],
            "look": {"yaw": to_keys(look_yaw, 0.3), "pitch": to_keys(look_pitch, 0.3)},
            "blinks": blinks,
        }
    # blush: expression channel (embarrassed) combined with scripted/automatic blush FX events
    for cid in cast_ids:
        segs_b = [(e["frame"] - FRAME_START, e["end_frame"] - FRAME_START, 0.9) for e in fx_events
                  if e["character"] == cid and e["type"] == "blush"]
        if not segs_b:
            continue
        fx_curve = ease_track(segs_b, n, ramp=8)
        prev = np.zeros(n, dtype=np.float32)
        if faces[cid]["blush"]:
            xs = [k[0] - FRAME_START for k in faces[cid]["blush"]]
            ys = [k[1] for k in faces[cid]["blush"]]
            prev = np.interp(np.arange(n), xs, ys).astype(np.float32)
        faces[cid]["blush"] = to_keys(np.clip(np.maximum(prev, fx_curve), 0, 1))
    fx_events = [e for e in fx_events if e["type"] != "blush"]
    return faces, _dedupe_fx(fx_events)


def _fx(cid: str, kind: str, beat: dict, fps: int, inten: float) -> dict:
    t0 = beat["start"] + 0.15
    dur = max(1.0, min(2.6, beat["end"] - beat["start"] + 0.3))
    return {"character": cid, "type": kind, "frame": FRAME_START + int(round(t0 * fps)),
            "end_frame": FRAME_START + int(round((t0 + dur) * fps)), "intensity": round(inten, 3), "beat": beat["id"]}


def _dedupe_fx(events: list[dict]) -> list[dict]:
    events.sort(key=lambda e: (e["character"], e["type"], e["frame"]))
    out: list[dict] = []
    for e in events:
        if out and out[-1]["character"] == e["character"] and out[-1]["type"] == e["type"] and \
                e["frame"] <= out[-1]["end_frame"]:
            out[-1]["end_frame"] = max(out[-1]["end_frame"], e["end_frame"])
            continue
        out.append(e)
    return sorted(out, key=lambda e: e["frame"])


def plan_blinks(n: int, fps: int, rng: random.Random, mood: np.ndarray, turns: list[int], cuts: list[int],
                emo_frames: list[int], rate: float = 1.0) -> tuple[np.ndarray, list[list[int]]]:
    starts: list[int] = []
    t = rng.uniform(0.5, 2.5) * fps
    while t < n:
        starts.append(int(t))
        gap = min(6.0, max(2.0, rng.gammavariate(4.0, 0.9))) / max(0.3, rate)
        t += gap * fps
    triggered = []
    for f in turns:
        if rng.random() < 0.55:
            triggered.append(max(0, f - 1))
    for f in cuts:
        if rng.random() < 0.3:
            triggered.append(f + rng.randint(1, 3))
    for f in emo_frames:
        if rng.random() < 0.7:
            triggered.append(f + rng.randint(0, 2))
    # triggered blinks replace the nearest random blink so the overall rate stays natural
    for f in triggered:
        if starts:
            j = min(range(len(starts)), key=lambda i: abs(starts[i] - f))
            if abs(starts[j] - f) < 1.6 * fps:
                starts[j] = f
                continue
        starts.append(f)
    starts = sorted(set(s for s in starts if 0 <= s < n))
    merged: list[int] = []
    for s in starts:  # at least 1.2 s between blinks (double blinks are added below)
        if not merged or s - merged[-1] > int(1.2 * fps):
            merged.append(s)
    curve = np.zeros(n, dtype=np.float32)
    blinks = []
    scale = fps / 30.0
    for s in merged:
        slow = float(mood[min(n - 1, s)]) > 0.4
        close, hold, open_ = (3, 2, 6) if slow else (2, 1, 3)
        close, hold, open_ = [max(1, int(round(x * scale))) for x in (close, hold, open_)]
        seq = list(np.linspace(0, 1, close + 1)[1:]) + [1.0] * hold + list(np.linspace(1, 0, open_ + 1)[1:])
        for k, v in enumerate(seq):
            if s + k < n:
                curve[s + k] = max(curve[s + k], v)
        blinks.append([s + FRAME_START, len(seq)])
        if rng.random() < 0.1 and not slow:  # double blink
            s2 = s + len(seq) + int(0.12 * fps)
            for k, v in enumerate(seq):
                if s2 + k < n:
                    curve[s2 + k] = max(curve[s2 + k], v)
    return curve, blinks


def _rel_angles(blocking: dict, cid: str, target: tuple[float, float, float], t: float) -> tuple[float, float]:
    x, y, yaw = position_at(blocking, cid, t)
    hx, hy, hz = head_point(blocking, cid, t)
    dx, dy, dz = target[0] - hx, target[1] - hy, target[2] - hz
    ang = math.degrees(math.atan2(dx, -dy))
    rel = (ang - yaw + 180) % 360 - 180
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return rel, pitch


KEYWORD_TARGETS = {"window": "window", "door": "door", "clock": "clock", "table": "table", "stairs": "stairs",
                   "gap": "gap", "tower": "window", "gear": "clock"}


def plan_gaze(cid: str, timeline: dict, blocking: dict, fps: int, n: int, rng: random.Random):
    """Per-frame gaze (eye) offsets and head look angles for one character."""
    beats = timeline["beats"]
    cast = timeline["cast"]
    marks = blocking.get("marks", {})
    surfaces = blocking.get("surfaces", {})
    tgt_yaw = np.zeros(n, dtype=np.float32)
    tgt_pitch = np.zeros(n, dtype=np.float32)
    for f in range(0, n, 2):
        t = f / fps
        b = next((x for x in beats if x["start"] <= t < x["end"]), None)
        target = None
        if b:
            spk, add = b.get("speaker"), b.get("addressee")
            if spk == cid:
                other = add if add in cast and add != cid else next((c for c in cast if c != cid), None)
                target = head_point(blocking, other, t) if other else None
            elif spk:
                target = head_point(blocking, spk, t)
            else:
                action = (b.get("action") or "").lower()
                for kw, mk in KEYWORD_TARGETS.items():
                    if kw in action and mk in marks:
                        mx, my = marks[mk]
                        target = (mx, my, 1.4 if mk in ("window", "clock") else 0.6)
                        break
                if target is None and b.get("props") and surfaces.get("table_top"):
                    st = surfaces["table_top"]
                    target = (st[0], st[1], st[2])
                if target is None and b.get("actor") and b["actor"] != cid:
                    target = head_point(blocking, b["actor"], t)
        if target is None:
            continue
        yaw, pitch = _rel_angles(blocking, cid, target, t)
        tgt_yaw[f:f + 2] = yaw
        tgt_pitch[f:f + 2] = pitch
    # look-aways while thinking: speaker glances away at the start of longer lines
    for b in beats:
        if b.get("speaker") != cid or not b.get("audio"):
            continue
        dur = b["audio"]["end"] - b["audio"]["start"]
        if dur > 2.0 and (rng.random() < 0.4 or b.get("emotion") in ("confused", "embarrassed")):
            f0 = int((b["audio"]["start"] + rng.uniform(0.1, 0.4)) * fps)
            f1 = min(n, f0 + int(rng.uniform(0.4, 0.9) * fps))
            side = rng.choice([-1, 1])
            tgt_yaw[f0:f1] += side * rng.uniform(18, 30)
            tgt_pitch[f0:f1] += rng.uniform(6, 14) if b.get("emotion") != "embarrassed" else -12
    # head follows the target with a lag; eyes take the remainder (eyes lead the head)
    head_yaw = np.zeros(n, dtype=np.float32)
    head_pitch = np.zeros(n, dtype=np.float32)
    hy, hp, vy, vp = float(tgt_yaw[0]) * 0.6, float(tgt_pitch[0]) * 0.5, 0.0, 0.0
    k = (2 * math.pi / 22.0) ** 2
    c = 2 * math.sqrt(k)
    turns: list[int] = []
    prev_t = float(tgt_yaw[0])
    for i in range(n):
        goal_y = float(np.clip(tgt_yaw[i] * 0.65, -65, 65))
        goal_p = float(np.clip(tgt_pitch[i] * 0.55, -25, 25))
        vy += k * (goal_y - hy) - c * vy
        vp += k * (goal_p - hp) - c * vp
        hy += vy
        hp += vp
        head_yaw[i], head_pitch[i] = hy, hp
        if abs(float(tgt_yaw[i]) - prev_t) > 35:
            turns.append(i)
        prev_t = float(tgt_yaw[i])
    eye_yaw = np.clip(tgt_yaw - head_yaw, -EYE_RANGE_YAW, EYE_RANGE_YAW)
    eye_pitch = np.clip(tgt_pitch - head_pitch, -EYE_RANGE_PITCH, EYE_RANGE_PITCH)
    # eyes snap in ~2 frames (saccade-like) rather than easing
    gx = np.zeros(n, dtype=np.float32)
    gy = np.zeros(n, dtype=np.float32)
    ex, ey = float(eye_yaw[0]), float(eye_pitch[0])
    for i in range(n):
        ex += (float(eye_yaw[i]) - ex) * 0.55
        ey += (float(eye_pitch[i]) - ey) * 0.55
        gx[i], gy[i] = ex / EYE_RANGE_YAW, ey / EYE_RANGE_PITCH
    # micro saccades
    f = int(rng.uniform(0.3, 1.0) * fps)
    while f < n:
        hold = int(rng.uniform(0.4, 1.4) * fps)
        dx, dy = rng.uniform(-0.07, 0.07), rng.uniform(-0.05, 0.05)
        gx[f:f + hold] += dx
        gy[f:f + hold] += dy
        f += hold
    # the eyes object's +X is the character's left: positive relative yaw (target to the left) -> +gaze_x
    return gx, gy, head_yaw, head_pitch, turns


def reaction_gestures(timeline: dict, seed: int = 5) -> list[dict]:
    """Small body reactions for listeners (nod / gasp / recoil) as gesture events."""
    rng = random.Random(seed)
    out = []
    for b in timeline["beats"]:
        spk = b.get("speaker")
        if not spk:
            continue
        rexpr, rscale, gesture = REACTIONS.get(b.get("emotion", "neutral"), ("neutral", 0, None))
        if not gesture or float(b.get("intensity", 0.5)) < 0.5:
            continue
        for cid in timeline["cast"]:
            if cid == spk:
                continue
            if b.get("addressee") not in (None, cid) and rng.random() < 0.5:
                continue
            out.append({"t": round(b["start"] + rng.uniform(0.3, 0.6), 3), "type": "gesture", "character": cid,
                        "name": gesture, "intensity": round(float(b.get("intensity", 0.5)) * 0.6, 3),
                        "beat": b["id"], "duration": 1.0, "reaction": True})
    return out


def lipsync_offset_frames(timeline: dict, cid: str, audio: np.ndarray, sr: int, fps: int, max_lag: int = 5) -> float | None:
    """Estimate the lag (frames) between mouth openness and the speech envelope by cross-correlation."""
    from storyforge.performance.lipsync import cues_to_frames

    n = timeline["frames"]
    cues = [c for b in timeline["beats"] if b.get("speaker") == cid for c in b.get("mouth", [])]
    if not cues:
        return None
    fc = cues_to_frames(sorted(cues, key=lambda c: c["start"]), 0.0, fps)
    mouth = openness_curve(fc, n)
    hop = sr // fps
    env = np.array([np.sqrt(np.mean(audio[i * hop:(i + 1) * hop] ** 2)) if (i + 1) * hop <= len(audio) else 0.0
                    for i in range(n)], dtype=np.float32)
    if env.max() <= 0 or mouth.max() <= 0:
        return None
    env = (env - env.mean()) / (env.std() + 1e-9)
    m = (mouth - mouth.mean()) / (mouth.std() + 1e-9)
    best, best_lag = -1e9, 0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            v = float(np.dot(m[lag:], env[:n - lag]))
        else:
            v = float(np.dot(m[:n + lag], env[-lag:]))
        if v > best:
            best, best_lag = v, lag
    return float(best_lag)
