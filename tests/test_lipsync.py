"""Lip-sync: Rhubarb mouth shapes (A-H, X) -> frame-accurate shape keys."""

from __future__ import annotations

import numpy as np
import pytest

from storyforge.performance.lipsync import (
    OPENNESS,
    cues_to_frames,
    estimate_cues,
    frames_to_shape_keys,
    openness_curve,
    resolve_map,
    word_to_shapes,
)
from storyforge.quality.animation_gates import _best_lag, _spec_openness
from storyforge.scene_spec import FRAME_START, mouth_tracks

SHAPES = ["A", "B", "C", "D", "E", "F", "G", "H", "X"]


def test_every_rhubarb_shape_maps_to_shape_keys():
    m = resolve_map(None)
    for s in SHAPES:
        assert s in m
    assert OPENNESS["D"] == max(OPENNESS.values())  # wide open
    assert OPENNESS["A"] == OPENNESS["X"] == 0.0     # closed / rest


@pytest.mark.parametrize("fps", [30, 60])
def test_cues_land_on_exact_frames(fps):
    cues = [{"start": 0.0, "end": 0.1, "shape": "X"}, {"start": 0.1, "end": 0.25, "shape": "D"},
            {"start": 0.25, "end": 0.4, "shape": "B"}, {"start": 0.4, "end": 0.5, "shape": "X"}]
    fc = cues_to_frames(cues, 1.0, fps)
    starts = {c["shape"]: c["frame"] for c in fc}
    assert starts["D"] == round(1.1 * fps)
    assert starts["B"] == round(1.25 * fps)
    for a, b in zip(fc, fc[1:], strict=False):
        assert a["frame"] < b["frame"]


def test_tiny_cues_keep_a_frame_and_later_cue_wins():
    cues = [{"start": 0.0, "end": 0.01, "shape": "C"}, {"start": 0.01, "end": 0.2, "shape": "D"}]
    fc = cues_to_frames(cues, 0.0, 30)
    assert fc[0]["shape"] == "D"  # both land on frame 0: the later one is what you see


def test_shape_keys_reach_full_weight_on_the_cue_frame():
    fc = [{"frame": 10, "end_frame": 14, "shape": "D"}, {"frame": 14, "end_frame": 20, "shape": "B"}]
    keys = frames_to_shape_keys(fc, resolve_map(None), blend_frames=1)
    m = resolve_map(None)
    d_key = max(m["D"], key=m["D"].get)
    at = dict(keys[d_key])
    assert at[10] == pytest.approx(m["D"][d_key])
    assert at[9] == pytest.approx(0.0)


def test_text_based_estimate_produces_plausible_shapes():
    assert "B" in word_to_shapes("map") or "A" in word_to_shapes("map")  # bilabial closure
    words = [{"word": "Hello", "start": 0.0, "end": 0.3}, {"word": "there", "start": 0.35, "end": 0.7}]
    cues = estimate_cues(words, None, 0.8)
    assert cues[0]["start"] == 0.0 and cues[-1]["end"] <= 0.81
    assert all(c["shape"] in SHAPES for c in cues)


def test_mouth_tracks_shift_moves_every_key():
    tl = {"beats": [{"speaker": "milo", "mouth": [{"start": 0.0, "end": 0.2, "shape": "D"},
                                                   {"start": 0.2, "end": 0.4, "shape": "X"}]}]}
    base = mouth_tracks(tl, "milo", None, 30)
    shifted = mouth_tracks(tl, "milo", None, 30, shift=3)
    for k, seq in base.items():
        assert [f + 3 for f, _ in seq] == [f for f, _ in shifted[k]]
    assert min(f for seq in base.values() for f, _ in seq) >= FRAME_START - 1


def test_offset_estimator_finds_an_injected_lag():
    rng = np.random.default_rng(1)
    n = 300
    env = np.zeros(n, dtype=np.float32)
    for start in range(10, n - 20, 37):
        env[start:start + 12] = rng.uniform(0.4, 1.0)
    for lag in (-3, 0, 2):
        mouth = np.roll(env, lag)
        assert _best_lag(mouth, env) == pytest.approx(lag)


def test_openness_from_spec_tracks():
    tracks = {"mouth_D": [[1, 0.0], [5, 1.0], [9, 0.0]], "smile": [[1, 1.0]]}
    curve = _spec_openness(tracks, 12)
    assert curve[4] == pytest.approx(OPENNESS["D"])  # frame 5 -> index 4
    assert curve[0] == 0.0 and curve[-1] == 0.0
    fc = [{"frame": 2, "end_frame": 5, "shape": "D"}]
    assert openness_curve(fc, 8).max() == pytest.approx(OPENNESS["D"])
