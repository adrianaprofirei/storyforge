"""Film-grammar validation of a designed shot list (used by tests and the quality gates).

Rules checked:
* 180-degree rule: in dialogue shots the camera stays on the audience side of the line between
  the subject and the partner.
* no jump cuts: consecutive shots of the same subject differ by >= 2 sizes or >= 30 deg.
* eyelines: in singles the subject is framed with looking room toward the partner
  (screen position on the side opposite the direction they look).
* no dead frames: any shot longer than 1.5 s has camera motion or subject motion.
* pacing: shots between 0.5 s and 6 s.
"""

from __future__ import annotations

import math

from storyforge.cinematography.camera_math import on_audience_side
from storyforge.cinematography.designer import is_jump_cut
from storyforge.staging import head_point, position_at

DIALOGUE_TYPES = {"close_up", "medium_close", "medium", "over_the_shoulder", "two_shot", "extreme_close_up"}
SINGLES = {"close_up", "medium_close", "medium", "extreme_close_up"}


def check_180(shot: dict, blocking: dict) -> str | None:
    if shot["type"] not in DIALOGUE_TYPES or not shot.get("partner"):
        return None
    t = (shot["start"] + shot["end"]) / 2
    a = head_point(blocking, shot["subject"], t)[:2]
    b = head_point(blocking, shot["partner"], t)[:2]
    if math.dist(a, b) < 1e-3:
        return None
    cam = shot["camera"]["position"][:2]
    if not on_audience_side(a, b, cam):
        return f"{shot['id']}: camera crosses the 180-degree line ({shot['subject']}/{shot['partner']})"
    return None


def check_eyeline(shot: dict, blocking: dict) -> str | None:
    """Subject looking toward the partner must have room on that side of the frame."""
    if shot["type"] not in SINGLES or not shot.get("partner"):
        return None
    t = (shot["start"] + shot["end"]) / 2
    cam = shot["camera"]["position"]
    tgt = shot["camera"]["target"]
    sx, sy, _ = position_at(blocking, shot["subject"], t)
    px, py, _ = position_at(blocking, shot["partner"], t)
    fwd = (tgt[0] - cam[0], tgt[1] - cam[1])
    n = math.hypot(*fwd) or 1.0
    fwd = (fwd[0] / n, fwd[1] / n)
    right = (fwd[1], -fwd[0])
    look = (px - sx) * right[0] + (py - sy) * right[1]  # >0: partner is screen-right of the subject
    screen_x = shot["camera"].get("screen_x", 0.5)
    if abs(screen_x - 0.5) < 0.02:
        return None  # centred framing is neutral
    if look > 0.05 and screen_x > 0.5:
        return f"{shot['id']}: {shot['subject']} looks screen-right but is framed on the right (no looking room)"
    if look < -0.05 and screen_x < 0.5:
        return f"{shot['id']}: {shot['subject']} looks screen-left but is framed on the left (no looking room)"
    return None


def check_static(shot: dict) -> str | None:
    dur = shot["end"] - shot["start"]
    if dur > 1.5 and shot.get("movement", {}).get("type", "static") == "static" and not shot.get("has_subject_motion"):
        return f"{shot['id']}: static for {dur:.1f}s with no camera or subject motion"
    return None


def check_duration(shot: dict) -> str | None:
    dur = shot["end"] - shot["start"]
    if dur < 0.5:
        return f"{shot['id']}: too short ({dur:.2f}s)"
    if dur > 6.0:
        return f"{shot['id']}: too long ({dur:.2f}s) for vertical-short pacing"
    return None


def validate_shotlist(shotlist: dict, blocking: dict) -> dict[str, list[str]]:
    shots = shotlist["shots"]
    out: dict[str, list[str]] = {"180_rule": [], "jump_cuts": [], "eyelines": [], "static": [], "duration": []}
    for i, s in enumerate(shots):
        for key, fn in (("180_rule", lambda x: check_180(x, blocking)), ("eyelines", lambda x: check_eyeline(x, blocking)),
                        ("static", check_static), ("duration", check_duration)):
            msg = fn(s)
            if msg:
                out[key].append(msg)
        if i > 0 and is_jump_cut(shots[i - 1], s):
            out["jump_cuts"].append(f"{shots[i - 1]['id']} -> {s['id']}: jump cut on {s['subject']}")
    return out
