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
DIALOGUE_LUFS = -18.0    # pre-master level of every line; SFX and music sit well below it
SFX_BUS_DB = -7.0        # overall foley/SFX bus trim
# Delivery spec is <= -1 dBTP in the *encoded* file; lossy AAC adds ~0.2-0.4 dB of inter-sample
# overshoot, so the master is limited with codec headroom.
CEILING_DBTP = -1.5


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
        style_db = {"whisper": -4.0, "soft": -2.0, "normal": 0.0, "loud": 1.0, "shout": 2.0}.get(vol, 0.0)
        # every line is loudness-matched so dialogue stays consistent and on top of the mix
        lufs = dsp.integrated_loudness(clip, SR)
        gain_db = (DIALOGUE_LUFS - lufs if np.isfinite(lufs) else 0.0) + style_db
        st = dsp.to_stereo(clip, pan_for(b["speaker"], timeline["cast"], blocking))
        dsp.place(bus, st, a["start"], dsp.db_to_gain(gain_db), SR)
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


def dialogue_balance(dlg: np.ndarray, background: np.ndarray, activity: np.ndarray) -> dict:
    """How far dialogue sits above everything else while someone speaks (RMS over speech regions)."""
    m = activity > 0.5
    if m.sum() < SR * 0.5:
        return {"dialogue_over_background_db": None}
    d = float(np.sqrt(np.mean(dlg[m] ** 2)) + 1e-9)
    b = float(np.sqrt(np.mean(background[m] ** 2)) + 1e-9)
    return {"dialogue_over_background_db": round(20 * np.log10(d / b), 2)}


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


def _cue_clip(tag: str, seed: int) -> np.ndarray | None:
    from storyforge.audio.library import find_sfx, load

    entry = find_sfx(tag, seed)
    if entry is None:
        return None
    return load(entry["file"], stereo=False)


def render_cues(cues: list[dict], n: int, offset: float = 0.0) -> tuple[np.ndarray, list[dict]]:
    bus = np.zeros((n, 2), dtype=np.float32)
    placed = []
    for k, c in enumerate(cues):
        clip = _cue_clip(c["tag"], seed=int(c["t"] * 1000) + k)
        if clip is None:
            placed.append({**c, "missing": True})
            continue
        st = dsp.to_stereo(clip, c.get("pan", 0.0))
        dsp.place(bus, st, c["t"] + offset, dsp.db_to_gain(c.get("gain_db", -10)), SR)
        placed.append(c)
    return bus, placed


def sfx_bus_with_room(cues: list[dict], n: int, room: str, offset: float = 0.0) -> tuple[np.ndarray, list[dict]]:
    """SFX bus + a shared room reverb send so foley sits in the same space as the voices."""
    from storyforge.audio.voice import reverb

    dry, placed = render_cues(cues, n, offset)
    wet = np.stack([reverb(dry[:, 0], room)[:n], reverb(dry[:, 1], room)[:n]], axis=1) - dry * 0.95
    return ((dry + wet * 0.6) * dsp.db_to_gain(SFX_BUS_DB)).astype(np.float32), placed


def loop_to(audio: np.ndarray, n: int, xfade_s: float = 0.6) -> np.ndarray:
    if len(audio) >= n:
        return audio[:n]
    x = int(xfade_s * SR)
    out = np.zeros((n, audio.shape[1]), dtype=np.float32)
    pos = 0
    first = True
    while pos < n:
        seg = audio.copy()
        if not first and x > 0:
            ramp = np.linspace(0, 1, x, dtype=np.float32)[:, None]
            seg[:x] *= ramp
            out[pos:pos + x] *= (1 - ramp[: min(x, n - pos)])
        m = min(len(seg), n - pos)
        out[pos:pos + m] += seg[:m]
        pos += len(seg) - x
        first = False
    return out


def music_bus(plan: dict, n: int, activity: np.ndarray, offset: float = 0.0) -> np.ndarray:
    from storyforge.audio.library import find_music, load

    entry = find_music(plan["mood"])
    bus = np.zeros((n, 2), dtype=np.float32)
    if entry is None:
        return bus
    bed = load(entry["file"], stereo=True)
    s0 = int((plan["start"] + offset) * SR)
    s1 = min(n, int((plan["end"] + offset) * SR))
    body = loop_to(bed, max(0, s1 - s0))
    gain = np.full(len(body), dsp.db_to_gain(plan.get("bed_gain_db", -15)), dtype=np.float32)
    fi, fo = int(plan.get("fade_in", 0.4) * SR), int(plan.get("fade_out", 1.0) * SR)
    gain[:fi] *= np.linspace(0, 1, min(fi, len(gain)), dtype=np.float32)
    if fo and len(gain) > fo:
        gain[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
    if plan.get("pull_out") is not None:
        p = int((plan["pull_out"] + offset) * SR) - s0
        if 0 < p < len(gain):
            r = min(int(0.45 * SR), len(gain) - p)
            gain[p:p + r] *= np.linspace(1, 0.03, r, dtype=np.float32)
            gain[p + r:] *= 0.03
    if plan.get("swell") is not None:
        p = int((plan["swell"] + offset) * SR) - s0
        if 0 < p < len(gain):
            r = min(int(1.5 * SR), len(gain) - p)
            gain[p:p + r] *= np.linspace(1, 1.6, r, dtype=np.float32)
            gain[p + r:] *= 1.6
    duck = duck_envelope(activity)[s0:s0 + len(body)]
    bus[s0:s0 + len(body)] += body * (gain * duck[: len(gain)])[:, None]
    for st in plan.get("stings", []):
        clip = _cue_clip(st["tag"], 0)
        if clip is not None:
            dsp.place(bus, dsp.to_stereo(clip, 0.0), st["t"] + offset, dsp.db_to_gain(st.get("gain_db", -8)), SR)
    return bus


def ambience_bus(beds: list[dict], n: int) -> np.ndarray:
    from storyforge.audio.library import find_sfx, load

    bus = np.zeros((n, 2), dtype=np.float32)
    for b in beds:
        e = find_sfx(b["tag"])
        if e is None:
            continue
        mono = load(e["file"], stereo=False)
        st = loop_to(dsp.to_stereo(mono, 0.0), n, 1.0)
        bus += st * dsp.db_to_gain(b.get("gain_db", -28))
    return bus


def mix_episode(timeline: dict, episode_dir: Path, out_dir: Path, room: str, blocking: dict | None = None,
                sfx_cues: list[dict] | None = None, music_plan: dict | None = None,
                ambience: list[dict] | None = None, lead_seconds: float = 0.0,
                lead_cues: list[dict] | None = None) -> dict:
    """Full mix. `lead_seconds` prepends a recap lead-in (parts 2+): every story element is shifted by
    it and `lead_cues` (recap whooshes/swell) play inside it."""
    n_story = int((timeline["duration"] + 0.05) * SR)
    lead_n = int(lead_seconds * SR)
    n = n_story + lead_n
    dlg_story, act_story = dialogue_bus(timeline, episode_dir, room, n_story, blocking)
    dlg = np.zeros((n, 2), dtype=np.float32)
    dlg[lead_n:] = dlg_story
    activity = np.zeros(n, dtype=np.float32)
    activity[lead_n:] = act_story
    tone = room_tone(n, room)
    stems = {"dialogue": dlg, "room_tone": tone}
    mix = dlg + tone
    placed = []
    if sfx_cues:
        sb, placed = sfx_bus_with_room(sfx_cues, n, room, offset=lead_seconds)
        stems["sfx"] = sb
        mix = mix + sb
    if lead_cues:
        lb, _ = render_cues(lead_cues, n, 0.0)
        stems["recap"] = lb
        mix = mix + lb
    if music_plan:
        mb = music_bus(music_plan, n, activity, offset=lead_seconds)
        stems["music"] = mb
        mix = mix + mb
    if ambience:
        ab = ambience_bus(ambience, n)
        stems["ambience"] = ab
        mix = mix + ab
    bg = mix - dlg - tone
    stats_bal = dialogue_balance(dlg, bg, activity)
    mastered, stats = master(mix)
    stats.update(stats_bal)
    out_dir.mkdir(parents=True, exist_ok=True)
    dsp.save(out_dir / "mix.wav", mastered, SR)
    for name, stem in stems.items():
        dsp.save(out_dir / "stems" / f"{name}.wav", stem, SR)
    stats.update({"duration": round(n / SR, 3), "dialogue_activity": round(float(activity.mean()), 3),
                  "lead_seconds": lead_seconds, "sfx_cues": len(placed),
                  "missing_sfx": sorted({c["tag"] for c in placed if c.get("missing")})})
    return stats
