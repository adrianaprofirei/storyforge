"""Per-line voice preparation (provider-agnostic) and location-matched voice processing.

``prepare_line``: provider WAV -> 48 kHz mono, optional pitch shift (character voice), volume
styling for offline providers (whisper/shout), silence trim and peak normalisation. The result
is cached per line.

``process_dialogue`` (used by the mixer): broadcast-style voice chain applied to each placed
line: high-pass, mud cut, presence lift, de-esser, compressor, plus a room reverb matched to
the location (small room, hallway, large hall, outdoors) via convolution with a generated IR.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import signal

from storyforge.audio import dsp
from storyforge.util.ffmpeg import ffmpeg

SR = dsp.SR


def pitch_shift_file(src: Path, dst: Path, semitones: float) -> Path:
    """Formant-naive pitch shift that keeps duration (asetrate + atempo, works on any ffmpeg)."""
    ratio = 2 ** (semitones / 12.0)
    tempo = 1.0 / ratio
    chain = []
    t = tempo
    while t < 0.5:  # atempo accepts 0.5..2.0 per instance
        chain.append("atempo=0.5")
        t /= 0.5
    while t > 2.0:
        chain.append("atempo=2.0")
        t /= 2.0
    chain.append(f"atempo={t:.6f}")
    af = f"aresample={SR},asetrate={SR * ratio:.3f},aresample={SR}," + ",".join(chain)
    ffmpeg(["-i", str(src), "-af", af, "-ac", "1", "-ar", str(SR), str(dst)])
    return dst


def style_volume(audio: np.ndarray, volume: str) -> np.ndarray:
    if volume == "whisper":
        a = dsp.apply_biquad(audio, "highpass", 380, SR, q=0.6)
        rng = np.random.default_rng(7)
        breath = dsp.apply_biquad(rng.normal(0, 1, len(a)).astype(np.float32), "highpass", 2500, SR)
        env = np.abs(signal.hilbert(a)) if len(a) < SR * 20 else np.abs(a)
        env = signal.savgol_filter(env, 801 if len(env) > 801 else (len(env) // 2) * 2 + 1, 2) if len(env) > 5 else env
        return (a * 0.65 + breath * np.clip(env, 0, 1) * 0.12).astype(np.float32)
    if volume == "shout":
        a = dsp.apply_biquad(audio, "peak", 2400, SR, q=0.8, gain_db=4.0)
        return np.tanh(a * 1.6).astype(np.float32) / np.tanh(1.6)
    if volume == "soft":
        return dsp.apply_biquad(audio, "highshelf", 5000, SR, gain_db=-2.0)
    return audio


def prepare_line(src: Path, dst: Path, pitch_semitones: float = 0.0, volume: str = "normal",
                 apply_volume_style: bool = True) -> dict:
    work = src
    if abs(pitch_semitones) > 0.05:
        shifted = dst.with_suffix(".pitch.wav")
        pitch_shift_file(src, shifted, pitch_semitones)
        work = shifted
    audio = dsp.load(work, SR)
    if work != src:
        Path(work).unlink(missing_ok=True)
    audio = dsp.apply_biquad(audio, "highpass", 70, SR)
    if apply_volume_style:
        audio = style_volume(audio, volume)
    audio = dsp.trim_silence(audio, SR, thresh_db=-42, keep_s=0.04)
    audio = dsp.peak_normalize(audio, -3.0)
    audio = dsp.fade(audio, 0.005, 0.02, SR)
    dsp.save(dst, audio, SR)
    return {"duration": round(len(audio) / SR, 4), "sample_rate": SR}


# --------------------------------------------------------------------------- room reverb
ROOM_PRESETS = {
    #            rt60   pre-delay  early refl   wet mix   damping (lowpass Hz)
    "small_room": (0.32, 0.004, 6, 0.10, 6500),
    "medium_room": (0.55, 0.008, 8, 0.12, 6000),
    "hallway": (1.05, 0.012, 10, 0.16, 5200),
    "large_hall": (1.6, 0.02, 12, 0.17, 4500),
    "outdoors": (0.18, 0.03, 3, 0.05, 9000),
}


def room_ir(room: str, sr: int = SR, seed: int = 11) -> np.ndarray:
    rt60, pre, n_early, _, damp = ROOM_PRESETS.get(room, ROOM_PRESETS["medium_room"])
    rng = np.random.default_rng(seed)
    n = int((rt60 * 1.2 + pre) * sr)
    t = np.arange(n) / sr
    tail = rng.normal(0, 1, n) * np.exp(-6.91 * t / max(rt60, 0.05))
    tail[: int(pre * sr)] = 0
    # early reflections: sparse taps in the first ~60 ms
    for _ in range(n_early):
        d = pre + rng.uniform(0.003, 0.06)
        idx = int(d * sr)
        if idx < n:
            tail[idx] += rng.choice([-1, 1]) * rng.uniform(0.3, 0.8) * np.exp(-6.91 * d / rt60)
    b, a = dsp.biquad("lowpass", damp, sr)
    ir = signal.lfilter(b, a, tail)
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    return ir.astype(np.float32)


def reverb(audio: np.ndarray, room: str, sr: int = SR) -> np.ndarray:
    wet_mix = ROOM_PRESETS.get(room, ROOM_PRESETS["medium_room"])[3]
    ir = room_ir(room, sr)
    wet = signal.fftconvolve(audio, ir)[: len(audio) + len(ir)]
    out = np.zeros(len(wet), dtype=np.float32)
    out[: len(audio)] += audio * (1 - wet_mix * 0.5)
    out += wet.astype(np.float32) * wet_mix
    return out


def process_dialogue(audio: np.ndarray, room: str = "medium_room", sr: int = SR) -> np.ndarray:
    a = dsp.apply_biquad(audio, "highpass", 90, sr, q=0.7)
    a = dsp.apply_biquad(a, "peak", 280, sr, q=1.0, gain_db=-2.5)      # mud cut
    a = dsp.apply_biquad(a, "peak", 3200, sr, q=0.9, gain_db=2.5)      # presence
    a = dsp.apply_biquad(a, "highshelf", 10000, sr, gain_db=1.5)       # air
    a = dsp.deess(a, sr, freq=6200, threshold_db=-30, max_reduction_db=7)
    a = dsp.compress(a, sr, threshold_db=-20, ratio=3.2, attack_s=0.004, release_s=0.09, makeup_db=3)
    return reverb(a, room, sr)
