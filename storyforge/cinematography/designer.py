"""Automatic shot designer following film grammar.

1. Cut points: one shot per beat by default, adjusted for J/L cuts (dialogue audio leads or
   trails the picture), long beats split on phrase boundaries, cuts moved onto gesture onsets
   (cut on action), and very short shots merged.
2. Coverage: hook framing, establishing/re-establishing wides, singles on the speaker, OTS
   pairs for exchanges, two-shots for banter, close-ups for intense lines, inserts on props,
   reactions when a line provokes one. Screenplay camera hints win.
3. Grammar: all cameras on the audience side of the action line (180-degree rule), speakers
   framed with looking room toward the addressee (correct eyelines), consecutive shots of the
   same subject must change size by >= 2 steps or angle by >= 30 deg (no jump cuts).
4. Motion: push-in on dramatic lines, handheld for tension, whip-pan / snap-zoom on punchlines,
   dolly on reveals, crane on payoffs, and a gentle drift on any static shot longer than 1.5 s.
5. Focus: the speaking character's eyes; focus pulls when the speaker changes inside a shot.

User overrides (shot list editor) are merged last, per shot id.
"""

from __future__ import annotations

import math
import random

from storyforge.cinematography.camera_math import (
    DEFAULT_FSTOP,
    DEFAULT_LENS,
    EYE_LINE,
    SHOT_SPANS,
    compose_target,
    distance_for_span,
    look_rotation,
    norm2,
    on_audience_side,
    rot2,
    size_index,
)
from storyforge.staging import head_point, is_moving, position_at

MIN_SHOT = 0.75
MAX_SHOT = 3.6
INTENSE = {"shocked", "scared", "sad", "angry", "determined", "excited"}
MOVE_FOR_HINT = {"push_in": "push_in", "pull_out": "pull_out", "dolly": "dolly", "handheld": "handheld",
                 "whip_pan": "whip_pan", "snap_zoom": "snap_zoom", "crane_up": "crane_up", "orbit": "orbit",
                 "pan": "pan", "truck": "truck"}
TYPE_FOR_HINT = {"push_in": None, "pull_out": None, "dolly": None, "handheld": None, "whip_pan": None,
                 "snap_zoom": None, "crane_up": "wide", "orbit": "medium", "pan": None, "truck": None,
                 "low_angle": None, "high_angle": None, "pov": "close_up", "reaction": "close_up"}


# ------------------------------------------------------------------ cut points
def _phrase_split_time(beat: dict) -> float | None:
    words = beat.get("words") or []
    if len(words) < 6:
        return None
    mid = (beat["start"] + beat["end"]) / 2
    best, best_d = None, 1e9
    for w in words[1:-2]:
        if w["word"][-1:] in ",.!?;:" or w["word"].endswith("..."):
            d = abs(w["end"] - mid)
            if d < best_d:
                best, best_d = w["end"] + 0.05, d
    return best


def plan_cuts(timeline: dict) -> list[dict]:
    """Return [{start, end, beat, kind, part}] picture segments (before coverage)."""
    beats = timeline["beats"]
    segs: list[dict] = []
    for i, b in enumerate(beats):
        start = 0.0 if i == 0 else b["start"]
        end = beats[i + 1]["start"] if i + 1 < len(beats) else timeline["duration"]
        segs.append({"start": start, "end": end, "beat": b["id"], "kind": "beat"})
    # J / L cuts at speaker changes
    by_id = {b["id"]: b for b in beats}
    for k in range(1, len(segs)):
        prev_b, cur_b = by_id[segs[k - 1]["beat"]], by_id[segs[k]["beat"]]
        if not (prev_b.get("audio") and cur_b.get("audio")) or prev_b.get("speaker") == cur_b.get("speaker"):
            continue
        if cur_b.get("camera_hint") in ("whip_pan", "snap_zoom") or cur_b.get("beat_type") in ("hook",):
            continue  # hard cut on purpose
        prev_line = prev_b.get("line") or ""
        if prev_line.endswith("?") or prev_b.get("beat_type") in ("joke", "reveal"):
            # L-cut: cut to the listener before the question/joke ends -> we see the reaction land
            cut = max(prev_b["start"] + 0.6, prev_b["audio"]["end"] - 0.35)
            kind = "L"
        elif (k % 2 == 0) or cur_b.get("intensity", 0.5) < 0.6:
            # J-cut: hear the reply over the end of the previous shot, then cut to the speaker
            cut = min(cur_b["audio"]["start"] + 0.28, cur_b["end"] - 0.6)
            kind = "J"
        else:
            continue
        if segs[k - 1]["start"] + MIN_SHOT < cut < segs[k]["end"] - MIN_SHOT:
            segs[k - 1]["end"] = cut
            segs[k]["start"] = cut
            segs[k]["transition"] = f"{kind}-cut"
    # split long shots on a phrase boundary
    out: list[dict] = []
    for s in segs:
        b = by_id[s["beat"]]
        if s["end"] - s["start"] > MAX_SHOT:
            t = _phrase_split_time(b)
            if t and s["start"] + MIN_SHOT < t < s["end"] - MIN_SHOT:
                out.append({**s, "end": t, "part": 0})
                out.append({**s, "start": t, "part": 1, "transition": "cut"})
                continue
        out.append({**s, "part": 0})
    # cut on action: snap a cut to a gesture onset within 0.3 s (cut 3 frames into the motion)
    fps = timeline["fps"]
    gestures = [e for e in timeline["events"] if e["type"] == "gesture"]
    for k in range(1, len(out)):
        c = out[k]["start"]
        near = [g for g in gestures if abs(g["t"] - c) < 0.3]
        if near:
            nc = near[0]["t"] + 3 / fps
            if out[k - 1]["start"] + MIN_SHOT < nc < out[k]["end"] - MIN_SHOT:
                out[k - 1]["end"] = nc
                out[k]["start"] = nc
                out[k]["cut_on_action"] = True
    # merge too-short segments into the previous one
    merged: list[dict] = []
    for s in out:
        if merged and s["end"] - s["start"] < MIN_SHOT * 0.8 and not by_id[s["beat"]].get("camera_hint") == "whip_pan":
            merged[-1]["end"] = s["end"]
            continue
        merged.append(s)
    return merged


# ------------------------------------------------------------------ coverage
def choose_type(b: dict, prev: dict | None, k: int, part: int) -> tuple[str, str]:
    hint = b.get("camera_hint")
    if hint in SHOT_SPANS:
        return hint, "camera hint"
    if hint == "establishing":
        return "establishing_wide", "camera hint"
    if hint in TYPE_FOR_HINT and TYPE_FOR_HINT[hint]:
        return TYPE_FOR_HINT[hint], f"hint {hint}"
    if k == 0:
        return "medium_wide", "hook: environment + subject"
    if b.get("motion"):
        return "wide", "movement needs geography"
    if not b.get("speaker"):
        if b.get("props"):
            return "insert", "prop action"
        return ("two_shot" if b.get("intensity", 0.5) < 0.8 else "wide"), "silent group beat"
    inten = float(b.get("intensity", 0.5))
    if part == 1:
        return "close_up" if inten >= 0.6 else "medium_close", "second half of a long line"
    if inten >= 0.85 or (b.get("emotion") in INTENSE and inten >= 0.7):
        return "close_up", "intense line"
    if b.get("addressee") and prev and prev.get("speaker") == b.get("addressee"):
        return "over_the_shoulder", "dialogue exchange"
    if inten >= 0.6:
        return "medium_close", "engaged line"
    return "medium", "conversational line"


def choose_move(b: dict, shot_type: str, dur: float, k: int) -> tuple[str, float]:
    hint = b.get("camera_hint")
    if hint in MOVE_FOR_HINT:
        return MOVE_FOR_HINT[hint], 1.0
    bt, emo, inten = b.get("beat_type"), b.get("emotion"), float(b.get("intensity", 0.5))
    if bt == "reveal":
        return "dolly", 1.0
    if bt == "payoff" and not b.get("speaker"):
        return "crane_up", 1.0
    if bt in ("joke",) and inten >= 0.85:
        return "snap_zoom", 1.0
    if emo in ("scared", "angry") and inten >= 0.6:
        return "handheld", inten
    if emo in INTENSE and inten >= 0.75 and shot_type in ("close_up", "medium_close", "medium"):
        return "push_in", inten
    if bt == "cliffhanger":
        return "push_in", 1.0
    if dur > 1.5:
        return "drift", 0.4  # never a dead static frame
    return "static", 0.0


def _subject_and_partner(b: dict, cast: list[str]) -> tuple[str, str | None]:
    subj = b.get("speaker") or b.get("actor") or cast[0]
    partner = b.get("addressee")
    if partner == subj or partner not in cast:
        partner = next((c for c in cast if c != subj), None)
    return subj, partner


def place_camera(shot: dict, blocking: dict, cast: list[str], t: float, rng: random.Random) -> dict:
    st = shot["type"]
    subj, partner = shot["subject"], shot.get("partner")
    lens = shot["lens_mm"]
    h = blocking["heights"][subj]["head_size"]
    eye = head_point(blocking, subj, t)
    sx, sy, syaw = position_at(blocking, subj, t)
    group = [head_point(blocking, c, t) for c in cast]
    if partner:
        px, py, _ = position_at(blocking, partner, t)
        to_partner = norm2((px - sx, py - sy))
    else:
        to_partner = norm2((math.sin(math.radians(syaw)), -math.cos(math.radians(syaw))))
    # which side of the subject is the audience on (perpendicular to the action line)
    perp = (to_partner[1], -to_partner[0])
    if perp[1] > 0:
        perp = (-perp[0], -perp[1])
    span = SHOT_SPANS[st] * h
    screen_x = 0.5
    if st in ("establishing_wide", "wide", "medium_wide"):
        cx = sum(p[0] for p in group) / len(group)
        cy = sum(p[1] for p in group) / len(group)
        width = max(p[0] for p in group) - min(p[0] for p in group) + 1.2
        tall = max(blocking["heights"][c]["head_top"] for c in cast)
        span = max(span, tall * (1.45 if st == "medium_wide" else 2.0), width / (9 / 16) * 0.95)
        dist = distance_for_span(span, lens)
        az = rng.uniform(-12, 12)
        d = rot2((0.0, -1.0), az)
        cam = (cx + d[0] * dist, cy + d[1] * dist, 0.9 if st != "establishing_wide" else 1.45)
        if st == "medium_wide" and subj:
            focus_pt = eye
            target_eye = eye
            screen_x = 0.5 + (0.1 if eye[0] < cx else -0.1)
        else:
            target_eye = (cx, cy, max(p[2] for p in group))
            focus_pt = eye
    elif st == "two_shot":
        a, b2 = eye, head_point(blocking, partner, t) if partner else eye
        mid = ((a[0] + b2[0]) / 2, (a[1] + b2[1]) / 2, (a[2] + b2[2]) / 2)
        sep = math.dist(a[:2], b2[:2]) + 0.9
        span = max(span, sep / (9 / 16) * 0.9)
        dist = distance_for_span(span, lens)
        cam = (mid[0] + perp[0] * dist, mid[1] + perp[1] * dist, mid[2] - 0.05)
        target_eye = mid
        focus_pt = eye
    elif st == "over_the_shoulder" and partner:
        p_eye = head_point(blocking, partner, t)
        back = norm2((p_eye[0] - eye[0], p_eye[1] - eye[1]))
        dist = distance_for_span(span, lens)
        # behind and beside the listener's shoulder, audience side
        cam = (eye[0] + back[0] * dist + perp[0] * 0.32, eye[1] + back[1] * dist + perp[1] * 0.32, p_eye[2] + 0.02)
        target_eye = eye
        focus_pt = eye
        screen_x = 0.42 if cross_sign(back, perp) > 0 else 0.58
    elif st == "insert":
        surf = blocking.get("surfaces", {}).get("table_top")
        if surf:
            tgt = (surf[0] + (sx - surf[0]) * 0.3, surf[1], surf[2] + 0.02)
        else:
            hx, hy, _ = position_at(blocking, subj, t)
            tgt = (hx, hy - 0.15, blocking["heights"][subj]["chest_z"] - 0.05)
        dist = distance_for_span(span, lens)
        d = rot2((0.0, -1.0), rng.uniform(-20, 20))
        cam = (tgt[0] + d[0] * dist * 0.75, tgt[1] + d[1] * dist * 0.75, tgt[2] + dist * 0.62)
        target_eye = tgt
        focus_pt = tgt
    else:  # singles: medium, medium_close, close_up, extreme_close_up
        dist = distance_for_span(span, lens)
        # camera rotated from the subject->partner direction toward the audience (3/4 view, inside the line)
        ang = 38 if st in ("close_up", "extreme_close_up") else 32
        side = 1 if cross_sign(to_partner, perp) > 0 else -1
        d = rot2(to_partner, ang * side)
        if d[1] > -0.2:  # keep it on the audience side
            d = norm2((d[0], -abs(d[1]) - 0.4))
        cam = (eye[0] + d[0] * dist, eye[1] + d[1] * dist, eye[2] - 0.03 * dist)
        target_eye = eye
        focus_pt = eye
        # looking room: subject looks toward the partner -> put them on the opposite third
        right = (d[1], -d[0])  # screen-right direction seen from camera
        look_x = to_partner[0] * (-right[0]) + to_partner[1] * (-right[1])
        screen_x = 0.42 if look_x > 0 else 0.58
    if shot.get("angle") == "low_angle":
        cam = (cam[0], cam[1], max(0.25, cam[2] - 0.35))
    elif shot.get("angle") == "high_angle":
        cam = (cam[0], cam[1], cam[2] + 0.45)
    # 180-degree rule: mirror the camera across the action line if it ended up on the wrong side
    if partner and st not in ("establishing_wide", "wide", "insert"):
        a2 = (eye[0], eye[1])
        b2 = head_point(blocking, partner, t)[:2]
        if not on_audience_side(a2, b2, cam[:2]):
            ax, ay = b2[0] - a2[0], b2[1] - a2[1]
            n = math.hypot(ax, ay) or 1
            ax, ay = ax / n, ay / n
            vx, vy = cam[0] - a2[0], cam[1] - a2[1]
            dot = vx * ax + vy * ay
            mx, my = 2 * (a2[0] + ax * dot) - cam[0], 2 * (a2[1] + ay * dot) - cam[1]
            cam = (mx, my, cam[2])
    screen_y = EYE_LINE.get(st, 0.66)
    aim = compose_target(target_eye, cam, lens, screen_x, screen_y)
    return {"position": [round(c, 4) for c in cam], "target": [round(c, 4) for c in aim],
            "rotation": [round(r, 5) for r in look_rotation(cam, aim)],
            "focus_point": [round(c, 4) for c in focus_pt], "screen_x": screen_x, "screen_y": screen_y}


def cross_sign(a, b) -> float:
    return math.copysign(1.0, a[0] * b[1] - a[1] * b[0] or 1.0)


def camera_angle_deg(shot_a: dict, shot_b: dict) -> float:
    pa, ta = shot_a["camera"]["position"], shot_a["camera"]["target"]
    pb, tb = shot_b["camera"]["position"], shot_b["camera"]["target"]
    va = norm2((ta[0] - pa[0], ta[1] - pa[1]))
    vb = norm2((tb[0] - pb[0], tb[1] - pb[1]))
    dot = max(-1.0, min(1.0, va[0] * vb[0] + va[1] * vb[1]))
    return math.degrees(math.acos(dot))


def is_jump_cut(a: dict, b: dict) -> bool:
    if a["subject"] != b["subject"] or a["type"] == "insert" or b["type"] == "insert":
        return False
    return abs(size_index(a["type"]) - size_index(b["type"])) < 2 and camera_angle_deg(a, b) < 30


def _alt_type(t: str) -> str:
    i = size_index(t)
    return {0: "medium_close", 1: "medium", 2: "close_up", 3: "close_up", 4: "close_up", 5: "close_up",
            6: "close_up", 7: "medium_close", 8: "medium"}.get(i, "close_up")


def design_shots(timeline: dict, blocking: dict, overrides: dict | None = None, seed: int = 7) -> dict:
    rng = random.Random(seed)
    overrides = overrides or {}
    cast = timeline["cast"]
    beats = {b["id"]: b for b in timeline["beats"]}
    cuts = plan_cuts(timeline)
    shots: list[dict] = []
    prev_beat = None
    for k, c in enumerate(cuts):
        b = beats[c["beat"]]
        # (an L-cut segment starts before its beat: it shows this beat's speaker listening/reacting
        # while the previous line finishes, which is exactly the L-cut picture)
        subj, partner = _subject_and_partner(b, cast)
        st, why = choose_type(b, prev_beat, k, c.get("part", 0))
        if st == "two_shot" and not partner:
            st = "medium"
        shot = {"id": f"{c['beat']}_{c.get('part', 0) + 1}", "beat": c["beat"], "start": round(c["start"], 4),
                "end": round(c["end"], 4), "type": st, "subject": subj, "partner": partner,
                "transition": c.get("transition", "cut"), "cut_on_action": bool(c.get("cut_on_action")),
                "reason": why, "angle": b.get("camera_hint") if b.get("camera_hint") in ("low_angle", "high_angle") else None}
        shots.append(shot)
        prev_beat = b
    # lens / motion / camera placement
    for k, s in enumerate(shots):
        b = beats[s["beat"]]
        ov = overrides.get(s["id"], {})
        if ov.get("type"):
            s["type"] = ov["type"]
            s["reason"] = "user override"
        s["lens_mm"] = float(ov.get("lens_mm") or DEFAULT_LENS[s["type"]])
        s["fstop"] = float(ov.get("fstop") or DEFAULT_FSTOP[s["type"]])
        dur = s["end"] - s["start"]
        mv, amt = choose_move(b, s["type"], dur, k)
        if ov.get("movement"):
            mv, amt = ov["movement"], float(ov.get("movement_amount", 1.0))
        s["movement"] = {"type": mv, "amount": round(amt, 3)}
        if ov.get("subject") in cast:
            s["subject"] = ov["subject"]
        t_mid = (s["start"] + s["end"]) / 2
        s["camera"] = place_camera(s, blocking, cast, t_mid, rng)
        if ov.get("framing"):
            s["framing_override"] = ov["framing"]
    # no jump cuts: fix consecutive same-subject shots that are too similar
    for k in range(1, len(shots)):
        a, b2 = shots[k - 1], shots[k]
        if is_jump_cut(a, b2) and "override" not in b2["reason"]:
            b2["type"] = _alt_type(b2["type"])
            b2["lens_mm"] = float(DEFAULT_LENS[b2["type"]])
            b2["fstop"] = float(DEFAULT_FSTOP[b2["type"]])
            b2["reason"] += "; resized to avoid a jump cut"
            b2["camera"] = place_camera(b2, blocking, cast, (b2["start"] + b2["end"]) / 2, rng)
    # focus: speaker eyes, pulls when the speaker changes inside the shot
    for s in shots:
        pulls = []
        for b in timeline["beats"]:
            if b.get("speaker") and s["start"] + 0.2 < b["start"] < s["end"] - 0.2 and b["speaker"] != s["subject"]:
                pulls.append({"t": round(b["start"], 3), "to": b["speaker"], "duration": 0.4})
        s["focus"] = {"subject": s["subject"], "pulls": pulls}
        moving = any(is_moving(blocking, c, s["start"], s["end"]) for c in cast)
        s["has_subject_motion"] = moving
    return {"version": 1, "fps": timeline["fps"], "shots": shots}


def shot_at(shotlist: dict, t: float) -> dict | None:
    for s in shotlist["shots"]:
        if s["start"] <= t < s["end"]:
            return s
    return shotlist["shots"][-1] if shotlist["shots"] else None
