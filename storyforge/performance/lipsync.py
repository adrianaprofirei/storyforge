"""Lip-sync: Rhubarb Lip Sync (A-H, X mouth cues) + a built-in estimator fallback, and the
mapping from cues to a character's mouth controls with frame accuracy.

Rhubarb shapes (https://github.com/DanielSWolf/rhubarb-lip-sync#mouth-shapes):
  A  closed (M, B, P)          B  slightly open, teeth (K, S, T, EE)   C  open (EH, AE)
  D  wide open (AA)            E  rounded (AO, ER)                     F  puckered (UW, OW, W)
  G  F/V (teeth on lower lip)  H  L (tongue up)                        X  idle / rest
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import soundfile as sf

from storyforge.util.io import read_json
from storyforge.util.proc import run
from storyforge.util.text import bare_word

SHAPES = ["A", "B", "C", "D", "E", "F", "G", "H", "X"]

# How "open" each shape is (used for the lip-sync offset quality gate and jaw motion).
OPENNESS = {"A": 0.0, "B": 0.25, "C": 0.6, "D": 1.0, "E": 0.55, "F": 0.3, "G": 0.15, "H": 0.45, "X": 0.0}

# Default mapping of Rhubarb shapes onto the procedural character's mouth shape keys.
DEFAULT_SHAPE_KEYS = {s: {f"mouth_{s}": 1.0} for s in SHAPES if s != "X"} | {"X": {}}

# Mappings for common imported-character conventions (shape key name -> weight).
PRESET_MAPS = {
    "arkit": {
        "A": {"mouthClose": 0.8, "mouthPressLeft": 0.4, "mouthPressRight": 0.4},
        "B": {"jawOpen": 0.12, "mouthStretchLeft": 0.25, "mouthStretchRight": 0.25},
        "C": {"jawOpen": 0.35, "mouthStretchLeft": 0.2, "mouthStretchRight": 0.2},
        "D": {"jawOpen": 0.7},
        "E": {"jawOpen": 0.3, "mouthFunnel": 0.5},
        "F": {"jawOpen": 0.1, "mouthPucker": 0.8},
        "G": {"jawOpen": 0.08, "mouthRollLower": 0.6, "mouthUpperUpLeft": 0.2, "mouthUpperUpRight": 0.2},
        "H": {"jawOpen": 0.35, "tongueOut": 0.25},
        "X": {},
    },
    "vrm": {"A": {}, "B": {"I": 0.5}, "C": {"E": 0.7}, "D": {"A": 1.0}, "E": {"O": 0.7}, "F": {"U": 0.9},
            "G": {"I": 0.3}, "H": {"E": 0.5}, "X": {}},
    "oculus": {"A": {"viseme_PP": 1.0}, "B": {"viseme_kk": 1.0}, "C": {"viseme_E": 1.0}, "D": {"viseme_aa": 1.0},
               "E": {"viseme_O": 1.0}, "F": {"viseme_U": 1.0}, "G": {"viseme_FF": 1.0}, "H": {"viseme_nn": 1.0},
               "X": {"viseme_sil": 1.0}},
}


# --------------------------------------------------------------------------- Rhubarb
def rhubarb_version(exe: str) -> str:
    try:
        out = run([exe, "--version"], timeout=30).output
        m = re.search(r"(\d+\.\d+\.\d+)", out)
        return m.group(1) if m else "unknown"
    except Exception:
        return "unknown"


def run_rhubarb(exe: str, wav: Path, text: str, out_json: Path, recognizer: str = "pocketSphinx") -> list[dict]:
    dialog = out_json.with_suffix(".txt")
    dialog.write_text(text, encoding="utf-8")
    args = [exe, "-f", "json", "-r", recognizer, "--extendedShapes", "GHX", "-d", str(dialog), "-o", str(out_json),
            "-q", str(wav)]
    run(args, timeout=600)
    dialog.unlink(missing_ok=True)
    data = read_json(out_json)
    return [{"start": float(c["start"]), "end": float(c["end"]), "shape": c["value"]} for c in data.get("mouthCues", [])]


# --------------------------------------------------------------------------- estimator fallback
_DIGRAPHS = [("th", "B"), ("sh", "B"), ("ch", "B"), ("ph", "G"), ("oo", "F"), ("ou", "E"), ("ow", "F"),
             ("ee", "B"), ("ea", "C"), ("ai", "C"), ("ay", "C"), ("oy", "E"), ("qu", "F"), ("wh", "F")]
_LETTER = {"m": "A", "b": "A", "p": "A", "f": "G", "v": "G", "l": "H", "w": "F", "o": "E", "u": "F", "a": "D",
           "e": "C", "i": "C", "y": "C", "r": "E"}


def word_to_shapes(word: str) -> list[str]:
    w = bare_word(word)
    shapes, i = [], 0
    while i < len(w):
        two = w[i:i + 2]
        hit = next((s for d, s in _DIGRAPHS if d == two), None)
        if hit:
            shapes.append(hit)
            i += 2
            continue
        shapes.append(_LETTER.get(w[i], "B"))
        i += 1
    # collapse repeats and drop silent trailing 'e' effect
    out: list[str] = []
    for s in shapes:
        if not out or out[-1] != s:
            out.append(s)
    return out or ["B"]


def estimate_cues(words: list[dict], wav: Path | None = None, total: float | None = None) -> list[dict]:
    """Mouth cues from word timings (+ the audio envelope to close the mouth in pauses)."""
    cues: list[dict] = []
    t_prev = 0.0
    for w in words:
        s, e = float(w["start"]), float(w["end"])
        if s - t_prev > 0.06:
            cues.append({"start": t_prev, "end": s, "shape": "X"})
        shapes = word_to_shapes(w["word"])
        # vowel-heavy words keep each shape >= 50 ms; very short words merge
        n = max(1, min(len(shapes), int((e - s) / 0.05)))
        shapes = shapes[:n] if len(shapes) > n else shapes
        step = (e - s) / len(shapes)
        for k, sh in enumerate(shapes):
            cues.append({"start": s + k * step, "end": s + (k + 1) * step, "shape": sh})
        t_prev = e
    end_t = total if total is not None else t_prev
    if wav is not None and Path(wav).is_file():
        audio, sr = sf.read(str(wav), dtype="float32", always_2d=True)
        mono = audio.mean(axis=1)
        end_t = len(mono) / sr
        hop = int(sr * 0.01)
        n = len(mono) // hop
        if n:
            rms = np.sqrt((mono[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
            thr = max(np.percentile(rms, 95) * 0.06, 1e-4)
            for c in cues:  # close mouth where the audio is silent
                i0, i1 = int(c["start"] / 0.01), max(int(c["start"] / 0.01) + 1, int(c["end"] / 0.01))
                if c["shape"] != "X" and rms[i0:i1].size and rms[i0:i1].max() < thr:
                    c["shape"] = "X"
    if end_t > t_prev:
        cues.append({"start": t_prev, "end": end_t, "shape": "X"})
    merged: list[dict] = []
    for c in cues:
        if merged and merged[-1]["shape"] == c["shape"]:
            merged[-1]["end"] = c["end"]
        elif c["end"] - c["start"] > 1e-4:
            merged.append(dict(c))
    return [{"start": round(c["start"], 3), "end": round(c["end"], 3), "shape": c["shape"]} for c in merged]


# --------------------------------------------------------------------------- mapping to frames
def resolve_map(face_cfg: dict | None) -> dict[str, dict[str, float]]:
    face_cfg = face_cfg or {}
    m = face_cfg.get("viseme_map")
    if isinstance(m, str):
        return PRESET_MAPS.get(m, DEFAULT_SHAPE_KEYS)
    if isinstance(m, dict):
        out = {}
        for s in SHAPES:
            v = m.get(s, {})
            out[s] = {v: 1.0} if isinstance(v, str) else dict(v)
        return out
    return DEFAULT_SHAPE_KEYS


def cues_to_frames(cues: list[dict], offset_s: float, fps: int) -> list[dict]:
    """Quantise cues to frames. Every cue keeps at least one frame; when two cues land on the same
    frame the later one wins (it is the one the viewer sees on that frame)."""
    out: list[dict] = []
    for c in cues:
        f0 = int(round((offset_s + c["start"]) * fps))
        f1 = int(round((offset_s + c["end"]) * fps))
        if out and f0 <= out[-1]["frame"]:
            if out[-1]["frame"] == f0:
                out[-1]["shape"] = c["shape"]
                out[-1]["end_frame"] = max(f1, f0 + 1)
                continue
            f0 = out[-1]["frame"] + 1
        out.append({"frame": f0, "end_frame": max(f1, f0 + 1), "shape": c["shape"]})
    # merge consecutive identical shapes
    merged: list[dict] = []
    for k in out:
        if merged and merged[-1]["shape"] == k["shape"]:
            merged[-1]["end_frame"] = k["end_frame"]
        else:
            merged.append(k)
    return merged


def frames_to_shape_keys(frame_cues: list[dict], mapping: dict[str, dict[str, float]], blend_frames: int = 1,
                         strength: float = 1.0) -> dict[str, list[tuple[int, float]]]:
    """Per shape-key keyframes [(frame, value)]: the new shape reaches full weight exactly on its cue
    frame, crossfading from the previous shape over `blend_frames` frames."""
    keys: dict[str, list[tuple[int, float]]] = {}
    all_names = sorted({n for m in mapping.values() for n in m})
    prev: dict[str, float] = {}
    for cue in frame_cues:
        target = {n: mapping.get(cue["shape"], {}).get(n, 0.0) * strength for n in all_names}
        f = cue["frame"]
        for n in all_names:
            pv, tv = prev.get(n, 0.0), target[n]
            if abs(pv - tv) < 1e-6:
                continue
            seq = keys.setdefault(n, [])
            hold = f - blend_frames
            if not seq or seq[-1][0] < hold:
                seq.append((hold, pv))
            seq.append((f, tv))
        prev = target
    return keys


def openness_curve(frame_cues: list[dict], n_frames: int) -> np.ndarray:
    curve = np.zeros(n_frames, dtype=np.float32)
    for c in frame_cues:
        a, b = max(0, c["frame"]), min(n_frames, c["end_frame"])
        if b > a:
            curve[a:b] = OPENNESS.get(c["shape"], 0.0)
    return curve
