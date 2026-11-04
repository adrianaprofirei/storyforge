"""Audio DSP building blocks (numpy/scipy, float32, mono or stereo arrays shaped (n,) / (n, 2)).

Loudness follows ITU-R BS.1770-4 / EBU R128 via pyloudnorm; true peak is measured on a 4x
oversampled signal (the same definition ffmpeg's ebur128 uses).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

SR = 48000


def db_to_gain(db: float) -> float:
    return float(10 ** (db / 20.0))


def gain_to_db(g: float) -> float:
    return float(20 * np.log10(max(abs(g), 1e-12)))


def load(path: str | Path, sr: int = SR, mono: bool = True) -> np.ndarray:
    data, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    if mono:
        data = data.mean(axis=1)
    if file_sr != sr:
        data = resample(data, file_sr, sr)
    return data.astype(np.float32)


def save(path: str | Path, audio: np.ndarray, sr: int = SR, subtype: str = "PCM_24") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(p), np.asarray(audio, dtype=np.float32), sr, subtype=subtype)
    return p


def resample(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return audio
    from math import gcd

    g = gcd(int(sr_in), int(sr_out))
    return signal.resample_poly(audio, sr_out // g, sr_in // g, axis=0).astype(np.float32)


def to_stereo(audio: np.ndarray, pan: float = 0.0) -> np.ndarray:
    """Constant-power pan, pan in [-1, 1]."""
    if audio.ndim == 2:
        return audio
    theta = (pan + 1) * np.pi / 4
    return np.stack([audio * np.cos(theta), audio * np.sin(theta)], axis=1).astype(np.float32)


def place(bus: np.ndarray, clip: np.ndarray, start_s: float, gain: float = 1.0, sr: int = SR) -> None:
    """Add `clip` into `bus` at `start_s` seconds (in place, clipped to bus length)."""
    start = int(round(start_s * sr))
    if start >= len(bus) or len(clip) == 0:
        return
    if start < 0:
        clip = clip[-start:]
        start = 0
    end = min(len(bus), start + len(clip))
    bus[start:end] += clip[: end - start] * gain


def fade(audio: np.ndarray, fade_in_s: float = 0.0, fade_out_s: float = 0.0, sr: int = SR) -> np.ndarray:
    a = audio.copy()
    n_in, n_out = int(fade_in_s * sr), int(fade_out_s * sr)
    if n_in > 0:
        ramp = np.linspace(0, 1, min(n_in, len(a)), dtype=np.float32)
        a[: len(ramp)] *= ramp if a.ndim == 1 else ramp[:, None]
    if n_out > 0:
        ramp = np.linspace(1, 0, min(n_out, len(a)), dtype=np.float32)
        a[len(a) - len(ramp):] *= ramp if a.ndim == 1 else ramp[:, None]
    return a


def trim_silence(audio: np.ndarray, sr: int = SR, thresh_db: float = -45.0, keep_s: float = 0.03) -> np.ndarray:
    if len(audio) == 0:
        return audio
    mono = audio if audio.ndim == 1 else audio.mean(axis=1)
    peak = np.max(np.abs(mono)) or 1.0
    thr = peak * db_to_gain(thresh_db)
    idx = np.where(np.abs(mono) > thr)[0]
    if len(idx) == 0:
        return audio[: int(0.1 * sr)]
    keep = int(keep_s * sr)
    a, b = max(0, idx[0] - keep), min(len(audio), idx[-1] + keep)
    return audio[a:b]


def peak_normalize(audio: np.ndarray, target_db: float = -3.0) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak < 1e-6:
        return audio
    return (audio * (db_to_gain(target_db) / peak)).astype(np.float32)


# ------------------------------------------------------------------ filters
def biquad(kind: str, f0: float, sr: int = SR, q: float = 0.707, gain_db: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """RBJ audio-EQ-cookbook biquads: lowpass, highpass, peak, lowshelf, highshelf."""
    a_ = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    cosw, sinw = np.cos(w0), np.sin(w0)
    alpha = sinw / (2 * q)
    if kind == "lowpass":
        b = [(1 - cosw) / 2, 1 - cosw, (1 - cosw) / 2]
        a = [1 + alpha, -2 * cosw, 1 - alpha]
    elif kind == "highpass":
        b = [(1 + cosw) / 2, -(1 + cosw), (1 + cosw) / 2]
        a = [1 + alpha, -2 * cosw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * a_, -2 * cosw, 1 - alpha * a_]
        a = [1 + alpha / a_, -2 * cosw, 1 - alpha / a_]
    elif kind == "lowshelf":
        sq = 2 * np.sqrt(a_) * alpha
        b = [a_ * ((a_ + 1) - (a_ - 1) * cosw + sq), 2 * a_ * ((a_ - 1) - (a_ + 1) * cosw),
             a_ * ((a_ + 1) - (a_ - 1) * cosw - sq)]
        a = [(a_ + 1) + (a_ - 1) * cosw + sq, -2 * ((a_ - 1) + (a_ + 1) * cosw), (a_ + 1) + (a_ - 1) * cosw - sq]
    elif kind == "highshelf":
        sq = 2 * np.sqrt(a_) * alpha
        b = [a_ * ((a_ + 1) + (a_ - 1) * cosw + sq), -2 * a_ * ((a_ - 1) + (a_ + 1) * cosw),
             a_ * ((a_ + 1) + (a_ - 1) * cosw - sq)]
        a = [(a_ + 1) - (a_ - 1) * cosw + sq, 2 * ((a_ - 1) - (a_ + 1) * cosw), (a_ + 1) - (a_ - 1) * cosw - sq]
    else:
        raise ValueError(kind)
    b, a = np.array(b, dtype=np.float64), np.array(a, dtype=np.float64)
    return b / a[0], a / a[0]


def apply_biquad(audio: np.ndarray, kind: str, f0: float, sr: int = SR, q: float = 0.707,
                 gain_db: float = 0.0) -> np.ndarray:
    b, a = biquad(kind, f0, sr, q, gain_db)
    return signal.lfilter(b, a, audio, axis=0).astype(np.float32)


def envelope_follower(x: np.ndarray, sr: int, attack_s: float, release_s: float) -> np.ndarray:
    """Peak envelope with separate attack/release (vectorised by blocks for speed)."""
    x = np.abs(x if x.ndim == 1 else x.max(axis=1)).astype(np.float64)
    # downsample to 1 ms blocks, run the recursive filter there, then interpolate back
    block = max(1, sr // 1000)
    n = int(np.ceil(len(x) / block))
    pad = np.zeros(n * block)
    pad[: len(x)] = x
    blocks = pad.reshape(n, block).max(axis=1)
    a_att = np.exp(-1.0 / max(1e-6, attack_s * 1000))
    a_rel = np.exp(-1.0 / max(1e-6, release_s * 1000))
    env = np.zeros(n)
    e = 0.0
    for i, v in enumerate(blocks):
        coef = a_att if v > e else a_rel
        e = coef * e + (1 - coef) * v
        env[i] = e
    return np.interp(np.arange(len(x)) / block, np.arange(n), env).astype(np.float32)


def compress(audio: np.ndarray, sr: int = SR, threshold_db: float = -18.0, ratio: float = 3.0,
             attack_s: float = 0.005, release_s: float = 0.08, knee_db: float = 6.0,
             makeup_db: float = 0.0) -> np.ndarray:
    env = envelope_follower(audio, sr, attack_s, release_s)
    lvl = 20 * np.log10(env + 1e-9)
    over = lvl - threshold_db
    # soft knee
    gr = np.where(over <= -knee_db / 2, 0.0,
                  np.where(over >= knee_db / 2, over * (1 - 1 / ratio),
                           (1 - 1 / ratio) * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    gain = 10 ** ((-gr + makeup_db) / 20)
    return (audio * (gain if audio.ndim == 1 else gain[:, None])).astype(np.float32)


def deess(audio: np.ndarray, sr: int = SR, freq: float = 6500.0, threshold_db: float = -28.0,
          max_reduction_db: float = 8.0) -> np.ndarray:
    """Split-band de-esser: compress only the sibilance band when it gets loud."""
    sib = apply_biquad(audio, "highpass", freq, sr, q=0.9)
    rest = audio - sib
    env = envelope_follower(sib, sr, 0.001, 0.04)
    lvl = 20 * np.log10(env + 1e-9)
    red = np.clip((lvl - threshold_db) * 0.6, 0, max_reduction_db)
    g = 10 ** (-red / 20)
    return (rest + sib * (g if sib.ndim == 1 else g[:, None])).astype(np.float32)


# ------------------------------------------------------------------ loudness
def integrated_loudness(audio: np.ndarray, sr: int = SR) -> float:
    import pyloudnorm as pyln

    meter = pyln.Meter(sr)
    a = audio if audio.ndim == 2 else audio[:, None]
    if len(a) < int(0.5 * sr):
        a = np.concatenate([a, np.zeros((int(0.5 * sr) - len(a), a.shape[1]), dtype=a.dtype)])
    return float(meter.integrated_loudness(a.astype(np.float64)))


def true_peak_db(audio: np.ndarray, sr: int = SR, oversample: int = 4) -> float:
    a = audio if audio.ndim == 2 else audio[:, None]
    up = signal.resample_poly(a, oversample, 1, axis=0)
    peak = float(np.max(np.abs(up))) if len(up) else 0.0
    return gain_to_db(peak)


def sample_peak_db(audio: np.ndarray) -> float:
    return gain_to_db(float(np.max(np.abs(audio))) if len(audio) else 0.0)


def true_peak_limit(audio: np.ndarray, sr: int = SR, ceiling_db: float = -1.0, lookahead_s: float = 0.005,
                    release_s: float = 0.06, oversample: int = 4) -> np.ndarray:
    """Look-ahead brickwall limiter driven by the oversampled (true) peak."""
    a = audio if audio.ndim == 2 else audio[:, None]
    ceiling = db_to_gain(ceiling_db)
    up = signal.resample_poly(a, oversample, 1, axis=0)
    # per-sample true-peak estimate at base rate: max over each oversampled group
    n = len(a)
    tp = np.abs(up[: n * oversample]).reshape(n, oversample, a.shape[1]).max(axis=(1, 2))
    need = np.minimum(1.0, ceiling / np.maximum(tp, 1e-12))
    la = max(1, int(lookahead_s * sr))
    # running minimum over the look-ahead window so gain is already down when the peak arrives
    from scipy.ndimage import minimum_filter1d

    g = minimum_filter1d(need, size=2 * la + 1, mode="nearest")
    # smooth release (gain can drop instantly, recovers with release time constant)
    rel = np.exp(-1.0 / max(1.0, release_s * sr))
    out_g = np.empty_like(g)
    cur = 1.0
    # block-wise recursion for speed (1 ms blocks)
    block = max(1, sr // 1000)
    for i in range(0, n, block):
        target = float(g[i:i + block].min())
        if target < cur:
            cur = target
        else:
            cur = cur * rel ** block + target * (1 - rel ** block)
            cur = min(cur, target) if target < cur else cur
        out_g[i:i + block] = np.minimum(cur, g[i:i + block])
    res = a * out_g[:, None]
    # final safety: guarantee the ceiling even on pathological input
    tp_after = true_peak_db(res, sr, oversample)
    if tp_after > ceiling_db:
        res = res * db_to_gain(ceiling_db - tp_after - 0.05)
    return (res if audio.ndim == 2 else res[:, 0]).astype(np.float32)


def normalize_loudness(audio: np.ndarray, sr: int = SR, target_lufs: float = -14.0,
                       ceiling_dbtp: float = -1.0, iterations: int = 3) -> tuple[np.ndarray, dict]:
    """Gain to target integrated loudness, then true-peak limit; iterate because limiting
    lowers loudness slightly."""
    out = audio.astype(np.float32)
    for _ in range(iterations):
        lufs = integrated_loudness(out, sr)
        if not np.isfinite(lufs):
            break
        out = out * db_to_gain(target_lufs - lufs)
        out = true_peak_limit(out, sr, ceiling_db=ceiling_dbtp)
        if abs(integrated_loudness(out, sr) - target_lufs) < 0.25:
            break
    stats = {"integrated_lufs": round(integrated_loudness(out, sr), 2),
             "true_peak_dbtp": round(true_peak_db(out, sr), 2),
             "sample_peak_dbfs": round(sample_peak_db(out), 2)}
    return out, stats
