"""Timeline building and the automatic shot designer's film grammar."""

from __future__ import annotations

import copy

import pytest

from storyforge.cinematography.camera_math import DEFAULT_LENS
from storyforge.cinematography.designer import design_shots, is_jump_cut
from storyforge.cinematography.grammar import check_180, validate_shotlist
from storyforge.config import ASSETS_DIR
from storyforge.performance.lipsync import estimate_cues
from storyforge.staging import plan_blocking
from storyforge.timeline import build_timeline
from storyforge.util.io import read_json, read_yaml
from storyforge.util.text import split_words

SAMPLES = ASSETS_DIR / "samples"


def synthetic_voices(sp: dict) -> tuple[dict, dict]:
    """Voice + lip-sync manifests as the voice stages would write them (2.6 words/s)."""
    voices, lips = {"provider": "test", "silent": True, "lines": {}}, {"tool": "estimate", "lines": {}}
    for b in sp["beats"]:
        words = split_words(b.get("line") or "")
        if not b.get("speaker") or not words:
            continue
        step = 1 / 2.6
        ws = [{"word": w, "start": round(i * step, 3), "end": round((i + 1) * step - 0.02, 3)} for i, w in enumerate(words)]
        dur = len(words) * step + 0.1
        voices["lines"][b["id"]] = {"file": f"voices/{b['id']}.wav", "speaker": b["speaker"], "duration": dur, "words": ws}
        lips["lines"][b["id"]] = {"cues": estimate_cues(ws, None, dur)}
    return voices, lips


@pytest.fixture(scope="module")
def bible():
    return read_yaml(SAMPLES / "bible.yaml")


@pytest.fixture(scope="module")
def sp():
    return read_json(SAMPLES / "screenplays" / "part1.json")


@pytest.fixture(scope="module")
def timeline(sp, bible):
    v, lp = synthetic_voices(sp)
    return build_timeline(sp, v, lp, 30, bible, is_finale=False)


@pytest.fixture(scope="module")
def blocking(timeline):
    cast = read_yaml(SAMPLES / "cast.yaml")
    return plan_blocking(timeline, cast, {"preset": "library"})


def test_timeline_is_ordered_and_consistent(timeline, sp):
    beats = timeline["beats"]
    assert [b["id"] for b in beats] == [b["id"] for b in sp["beats"]]
    for a, b in zip(beats, beats[1:], strict=False):
        assert a["start"] < a["end"] <= b["start"] + 1e-6, (a["id"], b["id"])
    assert timeline["frames"] == pytest.approx(timeline["duration"] * timeline["fps"], abs=2)
    assert 30 <= timeline["duration"] <= 120


def test_spoken_beats_carry_audio_words_and_mouth_cues(timeline):
    for b in timeline["beats"]:
        if not b.get("speaker") or not b.get("line"):
            continue
        a = b["audio"]
        assert b["start"] - 1e-6 <= a["start"] < a["end"] <= b["end"] + 1e-6
        words = b["words"]
        assert words and all(w["start"] < w["end"] for w in words)
        assert words[0]["start"] >= a["start"] - 1e-6 and words[-1]["end"] <= a["end"] + 0.05
        assert all(x["start"] <= y["start"] for x, y in zip(words, words[1:], strict=False))
        assert b["mouth"], b["id"]


def test_hook_lands_fast(timeline):
    first = timeline["beats"][0]
    assert first["start"] < 0.5, "the hook must start within the first half second"


def test_duration_limit_cuts_the_timeline(sp, bible):
    v, lp = synthetic_voices(sp)
    tl = build_timeline(sp, v, lp, 30, bible, is_finale=False, duration_limit=5.0)
    assert tl["duration"] <= 5.5


def test_designed_shots_follow_film_grammar(timeline, blocking):
    sl = design_shots(timeline, blocking)
    shots = sl["shots"]
    assert shots[0]["start"] == pytest.approx(0.0, abs=0.05)
    assert shots[-1]["end"] == pytest.approx(timeline["duration"], abs=0.05)
    for a, b in zip(shots, shots[1:], strict=False):
        assert a["end"] == pytest.approx(b["start"], abs=1e-6), "shots must tile the timeline"
    violations = validate_shotlist(sl, blocking)
    assert violations["180_rule"] == []
    assert violations["jump_cuts"] == []
    assert violations["eyelines"] == []
    types = {s["type"] for s in shots}
    assert types & {"establishing_wide", "wide", "medium_wide"}, "an establishing/wide shot is required"
    assert types & {"close_up", "medium_close", "extreme_close_up"}, "coverage needs close shots"


def test_lens_conventions():
    assert 24 <= DEFAULT_LENS["establishing_wide"] <= 35
    assert 24 <= DEFAULT_LENS["wide"] <= 35
    assert 50 <= DEFAULT_LENS["close_up"] <= 85
    assert DEFAULT_LENS["extreme_close_up"] >= DEFAULT_LENS["close_up"]


def test_180_rule_detects_a_crossed_camera(timeline, blocking):
    sl = design_shots(timeline, blocking)
    shot = next(s for s in sl["shots"] if s.get("partner") and s["type"] in ("medium", "close_up", "medium_close"))
    assert check_180(shot, blocking) is None
    crossed = copy.deepcopy(shot)
    x, y, z = crossed["camera"]["position"]
    # mirror the camera through the line between subject and partner -> the other side of the line
    from storyforge.staging import head_point

    t = (shot["start"] + shot["end"]) / 2
    ax, ay, _ = head_point(blocking, shot["subject"], t)
    bx, by, _ = head_point(blocking, shot["partner"], t)
    dx, dy = bx - ax, by - ay
    n2 = dx * dx + dy * dy
    k = ((x - ax) * dx + (y - ay) * dy) / n2
    px, py = ax + k * dx, ay + k * dy
    crossed["camera"]["position"] = [2 * px - x, 2 * py - y, z]
    assert check_180(crossed, blocking) is not None


def test_jump_cut_detection():
    cam = {"position": [0.0, -3.0, 1.4], "target": [0.0, 0.0, 1.2]}
    a = {"subject": "milo", "type": "medium", "start": 0, "end": 2, "camera": cam}
    assert is_jump_cut(a, {**a, "start": 2, "end": 4})                 # same subject, size and angle
    assert not is_jump_cut(a, {**a, "type": "close_up", "start": 2})   # size change (>= 2 steps)
    assert not is_jump_cut(a, {**a, "subject": "zara", "start": 2})    # other subject
    turned = {"position": [2.6, -1.5, 1.4], "target": [0.0, 0.0, 1.2]}  # ~60 degrees around the subject
    assert not is_jump_cut(a, {**a, "start": 2, "camera": turned})


def test_user_override_wins(timeline, blocking):
    sl = design_shots(timeline, blocking)
    sid = sl["shots"][3]["id"]
    sl2 = design_shots(timeline, blocking, {sid: {"type": "extreme_close_up", "movement": "push_in", "lens_mm": 90}})
    s = next(x for x in sl2["shots"] if x["id"] == sid)
    assert (s["type"], s["movement"]["type"], s["lens_mm"]) == ("extreme_close_up", "push_in", 90)


def test_partners_turn_toward_each_other(timeline, blocking):
    for t in blocking.get("turns", []):
        assert abs(t["to"]) <= 75.0, "bodies never turn their back to the camera"
