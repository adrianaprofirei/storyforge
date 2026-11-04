"""Episode mixer: dialogue + foley/SFX + music (ducked) + room tone -> mastered stereo mix.

Buses are rendered in numpy at 48 kHz, then summed and mastered to -14 LUFS integrated with
a true-peak ceiling of -1 dBTP. Stems are written alongside the mix for the editable project.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from storyforge.audio import dsp
from storyforge.audio.voice import process_dialogue

SR = dsp.SR
TARGET_LUFS = -14.0
CEILING_DBTP = -1.0


def pan_for(character: str, cast: list[str], blocking: dict | None) -> float:
    """Gentle stereo placement from the character's stage position (kept narrow for mobile)."""
    if blocking and character in blocking.get("home", {}):
        x = blocking["home"][character][0]
        return float(np.clip(x / 2.5, -0.35, 0.35))
    if character in cast and len(cast) > 1:
        return -0.25 + 0.5 * cast.index(character) / (len(cast) - 1)
    return 0.0


def dialogue_bus(timeline: dict, episode_dir: Path, room: str, n: int, blocking: dict | None) -> tuple[np.ndarray, np.ndarray]:
    bus = np.zeros((n, 2), dtype=np.float32)
    activity = np.zeros(n, dtype=np.float32)  # 1 where dialogue plays (drives ducking)
    for b in timeline["beats"]:
        a = b.get("audio")
        if not a or a.get("silent"):
            continue
        clip = dsp.load(episode_dir / a["file"], SR)
        clip = process_dialogue(clip, room, SR)
        vol = (b.get("delivery") or {}).get("volume", "normal")
        gain_db = {"whisper": -5.0, "soft": -2.5, "normal": 0.0, "loud": 1.5, "shout": 2.5}.get(vol, 0.0)
        st = dsp.to_stereo(clip, pan_for(b["speaker"], timeline["cast"], blocking))
        dsp.place(bus, st, a["start"], dsp.db_to_gain(gain_db - 6.0), SR)
        i0 = int(a["start"] * SR)
        i1 = min(n, int(a["end"] * SR))
        activity[max(0, i0):i1] = 1.0
    return bus, activity


def room_tone(n: int, room: str, seed: int = 3) -> np.ndarray:
    """Never digital silence: a quiet, filtered noise bed matched to the room type."""
    rng = np.random.default_rng(seed)
    white = rng.normal(0, 1, (n, 2)).astype(np.float32)
    # pink-ish: cascade of lowpasses + a touch of low hum for interiors
    tone = dsp.apply_biquad(white, "lowpass", {"outdoors": 2500, "hallway": 1200}.get(room, 800), SR, q=0.5)
    tone = dsp.apply_biquad(tone, "highpass", 40, SR)
    if room != "outdoors":
        t = np.arange(n) / SR
        hum = (0.15 * np.sin(2 * np.pi * 60 * t) + 0.05 * np.sin(2 * np.pi * 120 * t)).astype(np.float32)
        tone += np.stack([hum, hum], axis=1) * 0.2
    level_db = {"outdoors": -48, "hallway": -52, "large_hall": -54}.get(room, -56)
    rms = float(np.sqrt(np.mean(tone ** 2)) + 1e-9)
    return (tone * (dsp.db_to_gain(level_db) / rms)).astype(np.float32)


def duck_envelope(activity: np.ndarray, depth_db: float = -11.0, attack_s: float = 0.12,
                  release_s: float = 0.45) -> np.ndarray:
    """Gain curve (linear) that dips music under dialogue with smooth attack/release."""
    env = dsp.envelope_follower(activity, SR, attack_s, release_s)
    env = np.clip(env / (env.max() or 1.0), 0, 1)
    return dsp.db_to_gain(0) * (1 - env) + dsp.db_to_gain(depth_db) * env


def master(mix: np.ndarray) -> tuple[np.ndarray, dict]:
    # gentle bus glue, then loudness + true-peak limiting
    glued = dsp.compress(mix, SR, threshold_db=-16, ratio=1.8, attack_s=0.02, release_s=0.25, knee_db=8)
    return dsp.normalize_loudness(glued, SR, TARGET_LUFS, CEILING_DBTP)


def mix_episode(timeline: dict, episode_dir: Path, out_dir: Path, room: str, blocking: dict | None = None,
                sfx_bus: np.ndarray | None = None, music_bus: np.ndarray | None = None,
                lead_seconds: float = 0.0) -> dict:
    n = int((timeline["duration"] + 0.05) * SR)
    dlg, activity = dialogue_bus(timeline, episode_dir, room, n, blocking)
    tone = room_tone(n, room)
    stems = {"dialogue": dlg, "room_tone": tone}
    mix = dlg + tone
    if sfx_bus is not None:
        sfx_bus = sfx_bus[:n] if len(sfx_bus) >= n else np.pad(sfx_bus, ((0, n - len(sfx_bus)), (0, 0)))
        stems["sfx"] = sfx_bus
        mix = mix + sfx_bus
    if music_bus is not None:
        music_bus = music_bus[:n] if len(music_bus) >= n else np.pad(music_bus, ((0, n - len(music_bus)), (0, 0)))
        ducked = music_bus * duck_envelope(activity)[:, None]
        stems["music"] = ducked
        mix = mix + ducked
    mastered, stats = master(mix)
    out_dir.mkdir(parents=True, exist_ok=True)
    dsp.save(out_dir / "mix.wav", mastered, SR)
    for name, stem in stems.items():
        dsp.save(out_dir / "stems" / f"{name}.wav", stem, SR)
    stats.update({"duration": round(n / SR, 3), "dialogue_activity": round(float(activity.mean()), 3)})
    return stats
