"""Quality gates on synthetic data with known problems, and the auto-fix bookkeeping."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from storyforge.audio import dsp
from storyforge.quality import animation_gates as ag
from storyforge.quality.gates import (
    gate_audio_clipping,
    gate_captions_safe_area,
    gate_continuity,
    gate_loudness,
)

FPS = 30


def make_analysis(n_frames=90, step=2, **overrides):
    """Two characters facing each other, idle, camera static: every gate passes."""
    chars = {"milo": {"has_animation": True, "head_size": 0.36, "torso_w": 0.32, "torso_d": 0.19},
             "zara": {"has_animation": True, "head_size": 0.34, "torso_w": 0.29, "torso_d": 0.18}}
    samples = []
    for f in range(1, n_frames + 1, step):
        breathe = 0.004 * np.sin(f / 6)
        ch = {}
        for cid, x, facing in (("milo", -0.5, 1.0), ("zara", 0.5, -1.0)):
            ch[cid] = {"head": [x, 0.0, 1.0 + breathe], "head_fwd": [facing, 0.0, 0.0],
                       "head_screen": [0.3 if cid == "milo" else 0.55, 0.5, 0.45 if cid == "milo" else 0.7, 0.7],
                       "hand.L": [x - 0.25, 0.0, 0.5 + breathe * 2], "hand.R": [x + 0.25, 0.0, 0.5 - breathe * 2],
                       "foot.L": [x - 0.08, 0.0, 0.065], "foot.R": [x + 0.08, 0.0, 0.065],
                       "hips": [x, 0.0, 0.45], "chest": [x, 0.0, 0.65 + breathe], "arm_elev": [-70.0, -70.0],
                       "root": [x, 0.0, 0.0]}
        samples.append({"frame": f, "camera": {"loc": [0.0, -3.0, 1.2], "rot": [1.5, 0.0, 0.0], "lens": 40.0},
                        "chars": ch})
    an = {"fps": FPS, "characters": chars,
          "shots": [{"id": "s1", "frame_start": 1, "frame_end": n_frames, "samples": samples}]}
    for k, v in overrides.items():
        an[k] = v
    return an


def idle_perf():
    return {"clips": {"idle": {"frames": 180, "contacts": {"foot.L": [[0, 180]], "foot.R": [[0, 180]]}}},
            "characters": {c: {"strips": [{"clip": "idle", "track": "base", "start": -10, "scale": 1.0,
                                           "repeat": 2.0}]} for c in ("milo", "zara")}}


def tl_with_line(speaker="milo", addressee="zara", t0=0.2, t1=2.6):
    return {"fps": FPS, "frames": 90, "cast": ["milo", "zara"],
            "beats": [{"id": "b01", "speaker": speaker, "addressee": addressee, "line": "Hello there friend",
                       "start": t0, "end": t1, "audio": {"start": t0, "end": t1},
                       "words": [{"word": "Hello", "start": t0, "end": t0 + 0.5}, {"word": "friend", "start": t1 - 0.5, "end": t1}]}]}


def test_clean_analysis_passes_everything():
    an = make_analysis()
    tl = tl_with_line()
    perf = idle_perf()
    shots = [{"id": "s1", "type": "two_shot", "reason": "", "start": 0, "end": 3}]
    for g in (ag.gate_rig(an), ag.gate_tpose(an, perf), ag.gate_foot_sliding(an, perf), ag.gate_interpenetration(an),
              ag.gate_speaker_on_screen(an, tl, shots), ag.gate_eyelines(an, tl)):
        assert g.status == "pass", (g.name, g.summary, g.details[:2])


def test_unrigged_character_fails():
    an = make_analysis()
    an["characters"]["zara"]["has_animation"] = False
    g = ag.gate_rig(an)
    assert g.status == "fail" and g.fix["action"] == "replan_performance"


def test_t_pose_is_detected_and_blames_the_active_clip():
    an = make_analysis()
    for s in an["shots"][0]["samples"][5:30]:
        s["chars"]["milo"]["arm_elev"] = [2.0, -3.0]
    g = ag.gate_tpose(an, idle_perf())
    assert g.status == "fail"
    assert g.details[0]["character"] == "milo" and "idle" in g.fix["clips"]["milo"]


def test_foot_sliding_while_planted():
    an = make_analysis()
    for i, s in enumerate(an["shots"][0]["samples"]):
        s["chars"]["milo"]["foot.L"][0] -= 0.012 * i  # planted foot skates 1.2 cm per sample
    g = ag.gate_foot_sliding(an, idle_perf())
    assert g.status == "fail" and g.fix["action"] == "strict_foot_lock" and g.fix["characters"] == ["milo"]


def test_swing_phase_of_a_walk_is_not_sliding():
    an = make_analysis()
    perf = idle_perf()
    perf["clips"]["walk"] = {"frames": 30, "contacts": {"foot.L": [[0, 12]], "foot.R": [[15, 27]]}}
    perf["characters"]["milo"]["strips"].append({"clip": "walk", "track": "locomotion", "start": 1, "scale": 1.0,
                                                 "repeat": 3.0, "blend_in": 0, "blend_out": 0})
    for s in an["shots"][0]["samples"]:
        f = s["frame"]
        phase = (f - 1) % 30
        if not phase <= 12:  # foot.L swings (moves) outside its planned contact
            s["chars"]["milo"]["foot.L"][0] += 0.03 * (phase - 12)
    assert ag.gate_foot_sliding(an, perf).status == "pass"


def test_hand_inside_torso_and_overlapping_bodies():
    an = make_analysis()
    for s in an["shots"][0]["samples"][:20]:
        s["chars"]["milo"]["hand.R"] = list(s["chars"]["milo"]["chest"])
    g = ag.gate_interpenetration(an)
    assert g.status == "fail" and "milo" in g.fix["hands"]
    an2 = make_analysis()
    for s in an2["shots"][0]["samples"]:
        s["chars"]["zara"]["hips"] = [-0.45, 0.0, 0.45]
    g2 = ag.gate_interpenetration(an2)
    assert g2.status == "fail" and g2.fix["pairs"]


def test_speaker_off_screen_requests_a_reframe():
    an = make_analysis()
    for s in an["shots"][0]["samples"]:
        s["chars"]["milo"]["head_screen"] = [1.3, 0.5, 1.5, 0.7]  # outside the frame
    g = ag.gate_speaker_on_screen(an, tl_with_line(), [{"id": "s1", "type": "close_up", "reason": "", "start": 0, "end": 3}])
    assert g.status == "fail" and g.fix["overrides"] == {"s1": {"subject": "milo"}}
    # a deliberate reaction shot is fine
    g2 = ag.gate_speaker_on_screen(an, tl_with_line(), [{"id": "s1", "type": "close_up", "reason": "listener reaction",
                                                          "start": 0, "end": 3}])
    assert g2.status == "pass"


def test_speaker_facing_away_from_addressee():
    an = make_analysis()
    for s in an["shots"][0]["samples"]:
        s["chars"]["milo"]["head_fwd"] = [-1.0, 0.0, 0.0]  # looks away from zara
    g = ag.gate_eyelines(an, tl_with_line())
    assert g.status == "fail" and "milo" in g.fix["characters"]


def test_static_shot_over_1_5_seconds():
    an = make_analysis()
    for s in an["shots"][0]["samples"]:  # freeze everybody
        for d in s["chars"].values():
            d["head"][2] = d["hand.L"][2] = d["hand.R"][2] = d["chest"][2] = 1.0
    g = ag.gate_static_shots(an)
    assert g.status == "fail" and g.fix["overrides"]["s1"]["movement"] == "push_in"
    assert ag.gate_static_shots(make_analysis()).status == "pass"  # breathing counts as motion


def test_captions_safe_area():
    ok = {"lines": [{"start": 0, "text": "hi", "width_px": 500, "play_w": 1080, "play_h": 1920, "margin_v": 520}]}
    assert gate_captions_safe_area(ok).status == "pass"
    wide = copy.deepcopy(ok)
    wide["lines"][0]["width_px"] = 1060
    low = copy.deepcopy(ok)
    low["lines"][0]["margin_v"] = 100
    assert gate_captions_safe_area(wide).status == "fail"
    assert gate_captions_safe_area(low).status == "fail"


def test_continuity_gate():
    assert gate_continuity(None).status == "skip"
    rep = {"counts": {"error": 1, "warning": 0, "info": 0}, "checked_against": ["p1"],
           "issues": [{"beat_id": "b03", "severity": "error", "status": "open", "kind": "object", "message": "x"}]}
    g = gate_continuity(rep)
    assert g.status == "fail" and g.fix["beats"] == ["b03"]


def _tone(seconds=6.0, level=0.3):
    t = np.arange(int(seconds * dsp.SR)) / dsp.SR
    x = level * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t))
    return np.stack([x, x], axis=1).astype(np.float32)


def test_clipping_gate(tmp_path):
    p = tmp_path / "mix.wav"
    loud = _tone(level=1.4).clip(-1, 1)
    dsp.save(p, loud, dsp.SR)
    assert gate_audio_clipping(p).status == "fail"
    dsp.save(p, _tone(level=0.3), dsp.SR)
    assert gate_audio_clipping(p).status == "pass"


def test_master_hits_streaming_loudness(tmp_path):
    from storyforge.audio.mixer import CEILING_DBTP, TARGET_LUFS, master

    rng = np.random.default_rng(3)
    speechy = _tone(8.0, 0.05) + rng.normal(0, 0.02, (int(8 * dsp.SR), 2)).astype(np.float32)
    out, stats = master(speechy)
    assert dsp.integrated_loudness(out) == pytest.approx(TARGET_LUFS, abs=0.5)
    assert dsp.true_peak_db(out) <= CEILING_DBTP + 0.1
    p = tmp_path / "mix.wav"
    dsp.save(p, out, dsp.SR)
    g = gate_loudness(p)
    assert g.status == "pass", g.summary
    dsp.save(p, out * 0.25, dsp.SR)  # 12 dB too quiet
    assert gate_loudness(p).status == "fail"


def test_autofix_bookkeeping(fresh_project):
    from storyforge.pipeline.context import EpisodeContext, RunOptions
    from storyforge.quality.autofix import apply_fixes, merged_overrides, section
    from storyforge.util.io import write_json

    eid = "fix_test"
    fresh_project.save_episode_meta(eid, {"title": "fix"})
    ctx = EpisodeContext(fresh_project, eid, RunOptions(preset="draft"), on_log=lambda _l: None)
    write_json(ctx.path("screenplay.final.json"), {"title": "x"})
    write_json(ctx.path("shot_overrides.json"), {"s2": {"type": "close_up"}})
    gates = [
        {"name": "static_shots", "fix": {"action": "shot_override", "overrides": {"s1": {"movement": "push_in"},
                                                                                     "s2": {"movement": "push_in"}}}},
        {"name": "lipsync_offset", "fix": {"action": "lipsync_shift", "shift": {"milo": -2}}},
        {"name": "foot_sliding", "fix": {"action": "strict_foot_lock", "characters": ["zara"]}},
        {"name": "captions_safe_area", "fix": {"action": "reflow_captions"}},
    ]
    applied = apply_fixes(ctx, gates)
    assert {a["gate"] for a in applied} == {"static_shots", "lipsync_offset", "foot_sliding", "captions_safe_area"}
    ov = merged_overrides(ctx)
    assert ov["s1"] == {"movement": "push_in"}
    assert ov["s2"] == {"type": "close_up"}, "the user's own override is never changed by an auto-fix"
    assert section(ctx, "performance")["lipsync_shift"] == {"milo": -2}
    assert section(ctx, "captions")["scale"] < 1.0
    # fixes belong to the script they were made for
    write_json(ctx.path("screenplay.final.json"), {"title": "changed"})
    assert section(ctx, "performance") == {} and merged_overrides(ctx) == {"s2": {"type": "close_up"}}
