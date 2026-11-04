"""Procedural sound synthesis for the built-in (CC0) SFX and music library.

Nothing here tries to be a sample library: these are clean, designed sounds (and simple music
beds) so StoryForge produces a complete mix offline. Drop real libraries into assets/sfx and
assets/music (with their license manifest) and they take priority by tag/mood.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

SR = 48000


def _t(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def env_adsr(n: int, a: float, d: float, s: float, r: float, sus_len: float | None = None) -> np.ndarray:
    a_n, d_n, r_n = int(a * SR), int(d * SR), int(r * SR)
    s_n = max(0, n - a_n - d_n - r_n) if sus_len is None else int(sus_len * SR)
    e = np.concatenate([np.linspace(0, 1, max(1, a_n)), np.linspace(1, s, max(1, d_n)), np.full(s_n, s),
                        np.linspace(s, 0, max(1, r_n))])
    if len(e) < n:
        e = np.pad(e, (0, n - len(e)))
    return e[:n].astype(np.float32)


def exp_decay(n: int, tau: float) -> np.ndarray:
    return np.exp(-np.arange(n) / (tau * SR)).astype(np.float32)


def bandpass(x: np.ndarray, lo: float, hi: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, [max(20, lo), min(SR / 2 - 100, hi)], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x).astype(np.float32)


def lowpass(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, min(SR / 2 - 100, f), btype="low", fs=SR, output="sos")
    return signal.sosfilt(sos, x).astype(np.float32)


def highpass(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, max(20, f), btype="high", fs=SR, output="sos")
    return signal.sosfilt(sos, x).astype(np.float32)


def norm(x: np.ndarray, peak_db: float = -3.0) -> np.ndarray:
    p = float(np.max(np.abs(x))) or 1.0
    return (x * (10 ** (peak_db / 20) / p)).astype(np.float32)


def noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.normal(0, 1, n).astype(np.float32)


# ------------------------------------------------------------------ foley
FOOT = {  # surface: (thump Hz, click band, click amount, decay s, grit)
    "wood": (95, (900, 3500), 0.55, 0.06, 0.1),
    "tile": (140, (2500, 9000), 0.9, 0.035, 0.05),
    "carpet": (80, (300, 1500), 0.15, 0.05, 0.25),
    "grass": (70, (1500, 7000), 0.25, 0.08, 0.9),
    "concrete": (120, (1800, 7000), 0.7, 0.04, 0.35),
    "gravel": (90, (1200, 6000), 0.4, 0.09, 1.2),
    "metal": (180, (2000, 6000), 0.8, 0.12, 0.05),
}


def footstep(surface: str, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    f0, band, click_amt, decay, grit = FOOT.get(surface, FOOT["wood"])
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    f = f0 * rng.uniform(0.9, 1.1)
    thump = np.sin(2 * np.pi * f * t * (1 - 0.35 * t / 0.22)) * exp_decay(n, decay)
    click = bandpass(noise(n, rng), *band) * exp_decay(n, decay * 0.35) * click_amt
    gr = bandpass(noise(n, rng), 800, 5000) * exp_decay(n, decay * 1.6) * grit * 0.5
    if surface == "gravel" or surface == "grass":
        crack = np.zeros(n, dtype=np.float32)
        for _ in range(int(6 + grit * 8)):
            i = rng.integers(0, int(n * 0.6))
            crack[i:i + 60] += rng.normal(0, 1, len(crack[i:i + 60])) * rng.uniform(0.2, 0.6)
        gr += highpass(crack, 1500) * grit * 0.4
    if surface == "metal":
        thump += np.sin(2 * np.pi * 1200 * t) * exp_decay(n, 0.09) * 0.25
    return norm(thump * 0.8 + click + gr, -4.0)


def whoosh(dur: float = 0.45, seed: int = 0, up: bool = True) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    x = noise(n, rng)
    # sweep a bandpass across the duration (frame-wise filtering)
    out = np.zeros(n, dtype=np.float32)
    frames = 24
    for k in range(frames):
        a, b = k * n // frames, (k + 1) * n // frames
        u = k / (frames - 1)
        fc = 300 * (1 + 10 * (u if up else 1 - u))
        seg = bandpass(x[max(0, a - 512):b], fc * 0.6, fc * 1.6)
        out[a:b] = seg[-(b - a):]
    shape = np.sin(np.pi * np.linspace(0, 1, n)) ** 1.6
    return norm(out * shape, -4.0)


def impact(kind: str = "soft", seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    f = 60 if kind == "hard" else 85
    body = np.sin(2 * np.pi * f * t * (1 - 0.5 * t)) * exp_decay(n, 0.12 if kind == "hard" else 0.07)
    crack = bandpass(noise(n, rng), 600, 6000) * exp_decay(n, 0.025) * (0.8 if kind == "hard" else 0.35)
    return norm(body + crack, -3.0)


def pop(seed: int = 0) -> np.ndarray:
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    f = 900 * np.exp(-t * 25) + 300
    return norm(np.sin(2 * np.pi * np.cumsum(f) / SR) * exp_decay(n, 0.03), -4.0)


def boing(seed: int = 0) -> np.ndarray:
    n = int(0.6 * SR)
    t = np.arange(n) / SR
    f = 180 + 220 * np.exp(-t * 6) + 25 * np.sin(2 * np.pi * 9 * t) * np.exp(-t * 3)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * exp_decay(n, 0.22)
    return norm(x, -4.0)


def zip_slide(dur: float = 0.35, up: bool = True, seed: int = 0) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f0, f1 = (400, 1600) if up else (1600, 400)
    f = f0 * (f1 / f0) ** (t / dur)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / dur)
    return norm(x, -6.0)


def twinkle(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(1.0 * SR)
    out = np.zeros(n, dtype=np.float32)
    notes = [2093, 2637, 3136, 3520, 4186]
    for _ in range(6):
        start = int(rng.uniform(0, 0.55) * SR)
        f = rng.choice(notes)
        m = n - start
        t = np.arange(m) / SR
        out[start:] += (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2.76 * t)) * exp_decay(m, 0.18) * 0.4
    return norm(out, -6.0)


def shimmer(dur: float = 1.8, seed: int = 0) -> np.ndarray:
    """Magic glissando: rising sine partials with a soft noise swell."""
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    for k, base in enumerate([523, 659, 784, 1047, 1319]):
        f = base * (1 + 0.6 * t / dur)
        out += np.sin(2 * np.pi * np.cumsum(f) / SR + k) * 0.2
    out *= env_adsr(n, 0.4, 0.3, 0.7, 0.8)
    air = highpass(noise(n, rng), 4000) * env_adsr(n, 0.6, 0.2, 0.5, 0.8) * 0.15
    return norm(out + air, -5.0)


def bell(f0: float, dur: float, decay: float, seed: int = 0) -> np.ndarray:
    """Inharmonic bell (clock chime)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    partials = [(0.5, 1.0, 1.0), (1.0, 0.8, 0.9), (1.19, 0.6, 0.7), (1.5, 0.5, 0.6), (2.0, 0.45, 0.5),
                (2.51, 0.3, 0.4), (2.66, 0.25, 0.35), (3.01, 0.2, 0.3), (4.1, 0.12, 0.2)]
    out = np.zeros(n, dtype=np.float32)
    for ratio, amp, dk in partials:
        out += amp * np.sin(2 * np.pi * f0 * ratio * t + ratio) * exp_decay(n, decay * dk)
    strike = bandpass(noise(n, np.random.default_rng(seed)), 1000, 6000) * exp_decay(n, 0.01) * 0.5
    return norm(out + strike, -2.0)


def clock_chime(seed: int = 0) -> np.ndarray:
    return bell(196.0, 5.0, 2.2, seed)


def tick(seed: int = 0, high: bool = True) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(0.06 * SR)
    x = bandpass(noise(n, rng), 2500 if high else 1200, 8000 if high else 4000) * exp_decay(n, 0.006)
    t = np.arange(n) / SR
    x += np.sin(2 * np.pi * (3200 if high else 1800) * t) * exp_decay(n, 0.01) * 0.4
    return norm(x, -6.0)


def gears_start(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    dur = 3.0
    n = int(dur * SR)
    t = np.arange(n) / SR
    groan = lowpass(noise(n, rng), 300) * np.clip(t / 0.8, 0, 1) * 0.8
    creak_f = 90 + 40 * np.sin(2 * np.pi * 0.7 * t)
    creak = np.sign(np.sin(2 * np.pi * np.cumsum(creak_f) / SR)) * 0.15 * np.exp(-((t - 0.6) ** 2) / 0.2)
    out = groan + lowpass(creak.astype(np.float32), 1200)
    for k in range(int(dur / 0.5)):
        s = int((0.9 + k * 0.5) * SR)
        if s < n:
            tk = tick(seed + k, k % 2 == 0)
            out[s:s + len(tk)] += tk[: n - s] * 0.7
    return norm(out, -4.0)


def clink(seed: int = 0, material: str = "ceramic") -> np.ndarray:
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    fs = {"ceramic": (2100, 3900, 5600), "metal": (1800, 4700, 7200), "wood": (600, 1400, 2900)}[material]
    x = sum(np.sin(2 * np.pi * f * t) * exp_decay(n, 0.06 if material != "wood" else 0.02) * a
            for f, a in zip(fs, (1.0, 0.5, 0.3), strict=False))
    return norm(x, -6.0)


def key_jingle(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(0.6 * SR)
    out = np.zeros(n, dtype=np.float32)
    for _ in range(7):
        s = int(rng.uniform(0, 0.35) * SR)
        c = clink(int(rng.integers(0, 1000)), "metal") * rng.uniform(0.3, 0.8)
        out[s:s + len(c)] += c[: n - s]
    return norm(out, -6.0)


def key_turn(seed: int = 0) -> np.ndarray:
    n = int(0.7 * SR)
    out = np.zeros(n, dtype=np.float32)
    for k, at in enumerate((0.05, 0.28, 0.45)):
        tk = tick(seed + k, False)
        s = int(at * SR)
        out[s:s + len(tk)] += tk[: n - s]
    grind = bandpass(noise(n, np.random.default_rng(seed)), 300, 2000) * env_adsr(n, 0.05, 0.1, 0.4, 0.2) * 0.2
    return norm(out + grind, -5.0)


def click(seed: int = 0) -> np.ndarray:
    return tick(seed, True)


def beep(seed: int = 0, n_beeps: int = 3) -> np.ndarray:
    n = int(0.12 * n_beeps * 2 * SR)
    out = np.zeros(n, dtype=np.float32)
    for k in range(n_beeps):
        s = int(k * 0.24 * SR)
        m = int(0.09 * SR)
        t = np.arange(m) / SR
        out[s:s + m] += np.sin(2 * np.pi * (1760 if k % 2 == 0 else 2093) * t) * env_adsr(m, 0.005, 0.01, 0.8, 0.02)
    return norm(out, -8.0)


def zipper(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    dur = 0.5
    n = int(dur * SR)
    t = np.arange(n) / SR
    rate = 60 + 50 * t / dur
    am = (np.sin(2 * np.pi * np.cumsum(rate) / SR) > 0.3).astype(np.float32)
    x = bandpass(noise(n, rng), 1500, 7000) * am * np.sin(np.pi * t / dur)
    return norm(x, -6.0)


def creak(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    dur = 0.8
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 160 + 80 * np.sin(2 * np.pi * 0.9 * t + rng.uniform(0, 3))
    saw = signal.sawtooth(2 * np.pi * np.cumsum(f) / SR).astype(np.float32)
    x = bandpass(saw, 400, 2500) * np.sin(np.pi * t / dur) ** 2
    return norm(x, -7.0)


def roll(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    dur = 1.2
    n = int(dur * SR)
    t = np.arange(n) / SR
    rumble = lowpass(noise(n, rng), 900) * (1 - t / dur) * 0.6
    bumps = np.zeros(n, dtype=np.float32)
    for k in range(10):
        s = int(k * dur / 10 * SR)
        tk = tick(seed + k, False) * (1 - k / 12)
        bumps[s:s + len(tk)] += tk[: n - s] * 0.5
    return norm(rumble + bumps, -6.0)


def paper(seed: int = 0, dur: float = 0.5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    crinkle = np.zeros(n, dtype=np.float32)
    for _ in range(40):
        s = int(rng.uniform(0, dur * 0.9) * SR)
        m = int(rng.uniform(0.003, 0.015) * SR)
        crinkle[s:s + m] += rng.normal(0, 1, len(crinkle[s:s + m])) * rng.uniform(0.2, 1.0)
    return norm(bandpass(crinkle, 1200, 9000), -6.0)


def paper_slam(seed: int = 0) -> np.ndarray:
    a = impact("soft", seed)
    b = paper(seed, 0.4)
    n = max(len(a), len(b))
    out = np.zeros(n, dtype=np.float32)
    out[: len(a)] += a
    out[: len(b)] += b * 0.6
    return norm(out, -3.0)


def cloth(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(0.35 * SR)
    x = bandpass(noise(n, rng), 400, 3000) * env_adsr(n, 0.05, 0.1, 0.4, 0.15)
    return norm(x, -9.0)


def clap(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(0.2 * SR)
    x = bandpass(noise(n, rng), 800, 5000) * exp_decay(n, 0.02)
    return norm(x, -5.0)


def sting(kind: str, seed: int = 0) -> np.ndarray:
    """Musical stings: reveal (bright stab), cliffhanger (low hit + dissonant rise), payoff (major flourish)."""
    rng = np.random.default_rng(seed)
    if kind == "cliffhanger":
        dur = 3.2
        n = int(dur * SR)
        t = np.arange(n) / SR
        hit = impact("hard", seed)
        low = np.sin(2 * np.pi * 55 * t) * exp_decay(n, 1.2) * 0.7
        rise = sum(np.sin(2 * np.pi * f * (1 + 0.08 * t) * t) for f in (311, 330, 466)) * env_adsr(n, 1.2, 0.5, 0.6, 1.0) * 0.18
        out = low + rise
        out[: len(hit)] += hit
        return norm(out.astype(np.float32), -2.0)
    chord = {"reveal": (392, 494, 587, 784), "payoff": (523, 659, 784, 1047)}.get(kind, (440, 554, 659))
    dur = 2.4 if kind == "payoff" else 1.8
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    for k, f in enumerate(chord):
        start = int((k * 0.06 if kind == "payoff" else 0) * SR)
        m = n - start
        tt = t[:m]
        brass = signal.sawtooth(2 * np.pi * f * tt).astype(np.float32)
        brass = lowpass(brass, 2400) * env_adsr(m, 0.02, 0.25, 0.5, 0.9)
        out[start:] += brass * 0.25
    swell = highpass(noise(n, rng), 3000) * env_adsr(n, 0.01, 0.4, 0.1, 0.3) * 0.12
    cymbal = bandpass(noise(n, rng), 5000, 14000) * exp_decay(n, 0.6) * 0.15
    return norm(out + swell + cymbal, -2.0)


def reverse_swell(dur: float = 1.2, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    x = bandpass(noise(n, rng), 2000, 12000) * exp_decay(n, 0.35)
    return norm(x[::-1].copy(), -5.0)


def room_ambience(kind: str, dur: float = 8.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    if kind == "outdoors":
        base = lowpass(noise(n, rng), 1200) * 0.3
        t = np.arange(n) / SR
        for _ in range(int(dur * 0.8)):  # distant birds
            s = int(rng.uniform(0, dur - 0.5) * SR)
            m = int(0.25 * SR)
            tt = np.arange(m) / SR
            f = rng.uniform(2500, 4200) * (1 + 0.3 * np.sin(2 * np.pi * 12 * tt))
            base[s:s + m] += np.sin(2 * np.pi * np.cumsum(f) / SR) * env_adsr(m, 0.02, 0.05, 0.4, 0.1) * 0.08
        del t
        return norm(base, -12.0)
    if kind == "crowd":
        babble = np.zeros(n, dtype=np.float32)
        for _ in range(8):
            v = bandpass(noise(n, rng), rng.uniform(250, 400), rng.uniform(900, 1800))
            am = (signal.sosfilt(signal.butter(1, 4, fs=SR, output="sos"), rng.normal(0, 1, n)) > 0).astype(np.float32)
            babble += v * lowpass(am, 12)
        return norm(babble, -14.0)
    return norm(lowpass(noise(n, rng), 600), -18.0)


# ------------------------------------------------------------------ music
NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def chord_notes(root: str, quality: str, octave: int = 4) -> list[int]:
    base = 12 * (octave + 1) + NOTE[root]
    iv = {"maj": (0, 4, 7), "min": (0, 3, 7), "dim": (0, 3, 6), "sus": (0, 5, 7), "maj7": (0, 4, 7, 11),
          "min7": (0, 3, 7, 10), "7": (0, 4, 7, 10)}[quality]
    return [base + i for i in iv]


def pluck(freq: float, dur: float, seed: int = 0, bright: float = 0.5) -> np.ndarray:
    """Karplus-Strong plucked string (vectorised in blocks)."""
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    period = max(2, int(SR / freq))
    buf = rng.uniform(-1, 1, period).astype(np.float32)
    out = np.zeros(n, dtype=np.float32)
    damp = 0.996 - 0.004 * (1 - bright)
    i = 0
    while i < n:
        m = min(period, n - i)
        out[i:i + m] = buf[:m]
        buf = damp * 0.5 * (buf + np.roll(buf, -1))
        i += m
    return out * exp_decay(n, max(0.15, dur * 0.6))


def keys(freq: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = (np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * 2 * freq * t) * exp_decay(n, 0.3) +
         0.15 * np.sin(2 * np.pi * 3 * freq * t) * exp_decay(n, 0.15))
    return (x * env_adsr(n, 0.005, 0.4, 0.35, 0.3)).astype(np.float32)


def pad(freqs: list[float], dur: float, seed: int = 0, cutoff: float = 1800) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    x = np.zeros(n, dtype=np.float32)
    for f in freqs:
        for det in (-0.12, 0.0, 0.11):
            x += signal.sawtooth(2 * np.pi * f * (1 + det / 100) * t + rng.uniform(0, 6)).astype(np.float32)
    x = lowpass(x, cutoff, 2) * env_adsr(n, 0.6, 0.4, 0.8, 0.8)
    return (x / (len(freqs) * 3)).astype(np.float32)


def kick(seed: int = 0) -> np.ndarray:
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    f = 45 + 90 * np.exp(-t * 30)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * exp_decay(n, 0.09)).astype(np.float32)


def shaker(seed: int = 0) -> np.ndarray:
    n = int(0.08 * SR)
    return (highpass(noise(n, np.random.default_rng(seed)), 6000) * exp_decay(n, 0.02) * 0.4).astype(np.float32)


def snap(seed: int = 0) -> np.ndarray:
    n = int(0.15 * SR)
    return (bandpass(noise(n, np.random.default_rng(seed)), 1500, 7000) * exp_decay(n, 0.03) * 0.7).astype(np.float32)


MOODS = {
    #            bpm  key  progression (root, quality)                                      lead      perc
    "playful":   (112, "C", [("C", "maj"), ("A", "min"), ("F", "maj"), ("G", "maj")], "pluck", "bouncy"),
    "mysterious": (84, "D", [("D", "min"), ("A#", "maj"), ("G", "min"), ("A", "7")], "keys", "soft"),
    "tense":     (96, "E", [("E", "min"), ("C", "maj"), ("D", "sus"), ("B", "7")], "pluck", "pulse"),
    "sad":       (70, "A", [("A", "min"), ("F", "maj"), ("C", "maj"), ("E", "min")], "keys", "none"),
    "triumphant": (104, "D", [("D", "maj"), ("G", "maj"), ("A", "maj"), ("D", "maj")], "pluck", "march"),
    "calm":      (76, "F", [("F", "maj7"), ("D", "min7"), ("A#", "maj7"), ("C", "7")], "keys", "none"),
    "comedic":   (126, "G", [("G", "maj"), ("E", "min"), ("C", "maj"), ("D", "7")], "pluck", "bouncy"),
    "spooky":    (72, "C", [("C", "min"), ("G#", "maj"), ("F", "min"), ("G", "7")], "keys", "soft"),
}


def music_bed(mood: str, bars: int = 16, seed: int = 0) -> np.ndarray:
    """A loopable arrangement: pad chords, bass, a light melodic figure and percussion."""
    bpm, _key, prog, lead, perc = MOODS.get(mood, MOODS["playful"])
    rng = np.random.default_rng(seed + sum(map(ord, mood)))
    beat = 60.0 / bpm
    bar = 4 * beat
    n = int(bars * bar * SR)
    out = np.zeros(n + int(2 * SR), dtype=np.float32)

    def put(x, at, g=1.0):
        s = int(at * SR)
        e = min(len(out), s + len(x))
        out[s:e] += x[: e - s] * g

    for b in range(bars):
        root, q = prog[b % len(prog)]
        notes = chord_notes(root, q, 4)
        t0 = b * bar
        put(pad([midi_hz(m) for m in notes], bar + 0.6, seed + b, 1400 if mood in ("sad", "spooky", "mysterious") else 2200),
            t0, 0.55)
        bass = midi_hz(notes[0] - 24)
        for k in range(4 if perc != "none" else 2):
            put(pluck(bass, beat * 1.6, seed + b * 7 + k, 0.2), t0 + k * (bar / (4 if perc != "none" else 2)), 0.5)
        # melodic figure: arpeggio / motif on chord tones (varied every 4 bars)
        pattern = [0, 2, 1, 2, 0, 1, 2, 1] if (b // 4) % 2 == 0 else [2, 1, 0, 1, 2, 2, 1, 0]
        steps = 8 if bpm >= 96 else 4
        for k in range(steps):
            if rng.random() < (0.85 if steps == 8 else 0.95):
                m = notes[pattern[k % len(pattern)] % len(notes)] + 12
                f = midi_hz(m)
                dur = bar / steps * 1.4
                x = pluck(f, dur, seed + b * 13 + k, 0.7) if lead == "pluck" else keys(f, dur)
                put(x, t0 + k * bar / steps, 0.22 if lead == "pluck" else 0.18)
        if perc in ("bouncy", "march", "pulse"):
            for k in range(4):
                if perc != "pulse" or k % 2 == 0:
                    put(kick(), t0 + k * beat, 0.5 if k % 2 == 0 else 0.3)
            if perc in ("bouncy", "march"):
                for k in (1, 3):
                    put(snap(seed + k), t0 + k * beat, 0.25)
            for k in range(8):
                put(shaker(seed + k + b), t0 + k * beat / 2, 0.18)
        elif perc == "soft":
            for k in range(2):
                put(shaker(seed + k + b), t0 + (k * 2 + 1) * beat, 0.12)
    # loop: fold the tail into the start so the bed loops seamlessly
    tail = out[n:].copy()
    out = out[:n]
    out[: len(tail)] += tail
    out = lowpass(out, 9000, 1)
    return norm(out, -6.0)


def stereoize(x: np.ndarray, width: float = 0.25, seed: int = 0) -> np.ndarray:
    """Mono -> stereo with a short decorrelating delay (Haas) for width."""
    d = int(0.012 * SR * width / 0.25)
    left = x
    right = np.concatenate([np.zeros(d, dtype=np.float32), x[:-d] if d else x])
    return np.stack([left, right * 0.95 + left * 0.05], axis=1).astype(np.float32)


GENERATORS = {
    # file stem: (callable, tags)
    **{f"footstep_{s}_{i}": ((lambda s=s, i=i: footstep(s, i)), ["footstep", s]) for s in FOOT for i in range(4)},
    **{f"whoosh_{i}": ((lambda i=i: whoosh(0.45, i)), ["whoosh"]) for i in range(3)},
    "whoosh_fast": (lambda: whoosh(0.22, 7), ["whoosh", "fast"]),
    "whoosh_cloth": (lambda: cloth(3), ["cloth", "whoosh_soft"]),
    "impact_soft": (lambda: impact("soft", 1), ["impact", "thud", "land"]),
    "impact_hard": (lambda: impact("hard", 2), ["impact", "hit"]),
    "pop": (lambda: pop(1), ["pop", "cartoon"]),
    "boing": (lambda: boing(1), ["boing", "cartoon"]),
    "zip_up": (lambda: zip_slide(0.35, True), ["zip", "cartoon", "slide_whistle"]),
    "zip_down": (lambda: zip_slide(0.45, False), ["zip_down", "cartoon"]),
    "twinkle": (lambda: twinkle(2), ["twinkle", "sparkle"]),
    "magic_shimmer": (lambda: shimmer(1.8, 3), ["magic_shimmer", "shimmer", "magic"]),
    "clock_chime": (lambda: clock_chime(4), ["clock_chime", "bell", "chime"]),
    "clock_tick": (lambda: tick(5), ["tick", "clock_tick"]),
    "gears_start": (lambda: gears_start(6), ["gears_start", "gears", "machine"]),
    "clink_ceramic": (lambda: clink(1, "ceramic"), ["clink", "cup", "ceramic"]),
    "clink_metal": (lambda: clink(2, "metal"), ["clink_metal", "metal"]),
    "tap_wood": (lambda: clink(3, "wood"), ["tap", "wood_tap"]),
    "key_jingle": (lambda: key_jingle(7), ["key_jingle", "keys"]),
    "key_turn": (lambda: key_turn(8), ["key_turn", "lock"]),
    "flashlight_click": (lambda: click(9), ["flashlight_click", "click", "switch"]),
    "gadget_beep": (lambda: beep(10), ["gadget_beep", "beep", "electronic"]),
    "backpack_zip": (lambda: zipper(11), ["backpack_zip", "zipper"]),
    "floor_creak": (lambda: creak(12), ["floor_creak", "creak"]),
    "roll": (lambda: roll(13), ["roll", "rolling"]),
    "paper_rustle": (lambda: paper(14), ["paper", "rustle", "map"]),
    "paper_slam": (lambda: paper_slam(15), ["paper_slam", "slam"]),
    "clap": (lambda: clap(16), ["clap"]),
    "reveal_sting": (lambda: sting("reveal", 17), ["reveal_sting", "sting_reveal", "sting"]),
    "cliffhanger_sting": (lambda: sting("cliffhanger", 18), ["cliffhanger_sting", "sting_cliffhanger"]),
    "payoff_sting": (lambda: sting("payoff", 19), ["payoff_sting", "sting_payoff"]),
    "recap_swell": (lambda: reverse_swell(1.2, 20), ["recap", "swell", "reverse"]),
    "amb_outdoors": (lambda: room_ambience("outdoors", 10.0, 21), ["ambience", "outdoors"]),
    "amb_crowd": (lambda: room_ambience("crowd", 10.0, 22), ["ambience", "crowd"]),
}


def silence_check(x: np.ndarray) -> bool:
    return bool(np.max(np.abs(x)) > 1e-4) and not bool(np.isnan(x).any())
