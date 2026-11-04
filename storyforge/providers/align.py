"""Word-level alignment of a voice line to its script text.

Sources, in order (``ALIGNMENT_MODE=auto``):
1. provider timings (ElevenLabs character alignment) - passed in by the voices stage,
2. OpenAI Whisper API (``whisper-1``, word timestamps) when OPENAI_API_KEY is set,
3. local ``faster-whisper`` when installed,
4. heuristic: speech/pause segmentation of the energy envelope + syllable-weighted
   distribution of words inside speech regions (good enough for caption highlighting).

Recognised words are mapped back onto the *script* words (captions show what was written,
not what the recogniser heard) with a difflib sequence alignment; gaps are interpolated.
"""

from __future__ import annotations

import difflib
import importlib.util
from pathlib import Path

import numpy as np
import soundfile as sf

from storyforge.config import Settings
from storyforge.util.text import bare_word, split_words, syllables


def speech_regions(audio: np.ndarray, sr: int, frame_ms: float = 10.0, min_gap: float = 0.09,
                   rel_thresh_db: float = -32.0) -> list[tuple[float, float]]:
    """(start, end) seconds of voiced regions from a short-time RMS envelope."""
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    hop = max(1, int(sr * frame_ms / 1000))
    n = len(audio) // hop
    if n == 0:
        return []
    frames = audio[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-12)
    peak = np.percentile(db, 98)
    voiced = db > max(peak + rel_thresh_db, -60.0)
    regions, start = [], None
    for i, v in enumerate(voiced):
        t = i * hop / sr
        if v and start is None:
            start = t
        elif not v and start is not None:
            regions.append([start, t])
            start = None
    if start is not None:
        regions.append([start, n * hop / sr])
    merged: list[list[float]] = []
    for r in regions:
        if merged and r[0] - merged[-1][1] < min_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(a, b) for a, b in merged if b - a > 0.03]


def heuristic_alignment(text: str, wav: Path) -> list[dict]:
    words = split_words(text)
    if not words:
        return []
    audio, sr = sf.read(str(wav), dtype="float32", always_2d=False)
    total = len(audio) / sr if sr else 0.0
    regions = speech_regions(audio, sr) or [(0.0, max(total, 0.1))]
    # weight = syllables (+ trailing pause after punctuation handled by the regions)
    weights = [max(1, syllables(w)) for w in words]
    # assign words to regions proportionally to region duration, breaking on punctuation when possible
    region_durs = [b - a for a, b in regions]
    total_voiced = sum(region_durs) or 1.0
    total_w = sum(weights)
    out = []
    cum_target = np.cumsum([d / total_voiced * total_w for d in region_durs])
    ri, acc = 0, 0.0
    groups: list[list[int]] = [[] for _ in regions]
    for i, w in enumerate(weights):
        center = acc + w / 2
        while ri < len(regions) - 1 and center > cum_target[ri]:
            ri += 1
        groups[ri].append(i)
        acc += w
    for (a, b), idxs in zip(regions, groups, strict=False):
        if not idxs:
            continue
        gw = sum(weights[i] for i in idxs)
        t = a
        for i in idxs:
            d = (b - a) * weights[i] / gw
            out.append({"word": words[i], "start": round(t, 3), "end": round(t + d, 3)})
            t += d
    out.sort(key=lambda x: x["start"])
    # any word that ended up unassigned (shouldn't happen) gets interpolated
    if len(out) < len(words):
        return proportional_alignment(words, 0.0, total)
    return out


def proportional_alignment(words: list[str], start: float, end: float) -> list[dict]:
    weights = [max(1, syllables(w)) for w in words]
    tot = sum(weights) or 1
    t = start
    out = []
    for w, wt in zip(words, weights, strict=False):
        d = (end - start) * wt / tot
        out.append({"word": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


def map_to_script(script_text: str, recognised: list[dict], duration: float) -> list[dict]:
    """Project recognised word timings onto the script's words."""
    words = split_words(script_text)
    if not recognised:
        return proportional_alignment(words, 0.0, duration)
    a = [bare_word(w) for w in words]
    b = [bare_word(r["word"]) for r in recognised]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    timings: list[dict | None] = [None] * len(words)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                r = recognised[j1 + k]
                timings[i1 + k] = {"word": words[i1 + k], "start": r["start"], "end": r["end"]}
        elif tag == "replace" and (i2 - i1) > 0 and (j2 - j1) > 0:
            s, e = recognised[j1]["start"], recognised[j2 - 1]["end"]
            for k, item in enumerate(proportional_alignment(words[i1:i2], s, e)):
                timings[i1 + k] = item
    # interpolate the gaps
    i = 0
    while i < len(words):
        if timings[i] is None:
            j = i
            while j < len(words) and timings[j] is None:
                j += 1
            s = timings[i - 1]["end"] if i > 0 else 0.0
            e = timings[j]["start"] if j < len(words) else duration
            for k, item in enumerate(proportional_alignment(words[i:j], s, max(e, s + 0.05 * (j - i)))):
                timings[i + k] = item
            i = j
        else:
            i += 1
    return [t for t in timings if t is not None]


def whisper_openai(settings: Settings, wav: Path) -> list[dict] | None:
    import httpx

    try:
        with httpx.Client(timeout=120, headers={"Authorization": f"Bearer {settings.openai_api_key}"}) as c:
            with open(wav, "rb") as f:
                r = c.post(f"{settings.openai_base_url}/audio/transcriptions",
                           data={"model": "whisper-1", "response_format": "verbose_json",
                                 "timestamp_granularities[]": "word"},
                           files={"file": (wav.name, f, "audio/wav")})
        if r.status_code != 200:
            return None
        return [{"word": w["word"], "start": float(w["start"]), "end": float(w["end"])}
                for w in r.json().get("words", [])]
    except Exception:
        return None


def whisper_local(settings: Settings, wav: Path) -> list[dict] | None:
    if importlib.util.find_spec("faster_whisper") is None:
        return None
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(settings.whisper_local_model, device="auto", compute_type="int8")
        segments, _ = model.transcribe(str(wav), word_timestamps=True, language="en")
        out = []
        for seg in segments:
            for w in seg.words or []:
                out.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})
        return out
    except Exception:
        return None


def align_words(settings: Settings, text: str, wav: Path, provider_words: list[dict] | None = None,
                silent: bool = False) -> tuple[list[dict], str]:
    info = sf.info(str(wav))
    duration = info.frames / info.samplerate if info.samplerate else 0.0
    words = split_words(text)
    if not words:
        return [], "none"
    if silent:
        return proportional_alignment(words, 0.05, max(0.1, duration - 0.05)), "estimate"
    mode = settings.alignment_mode
    if provider_words and mode in {"auto", "provider"}:
        return map_to_script(text, provider_words, duration), "provider"
    if mode in {"auto", "openai"} and settings.openai_api_key:
        rec = whisper_openai(settings, wav)
        if rec:
            return map_to_script(text, rec, duration), "whisper_api"
    if mode in {"auto", "local"}:
        rec = whisper_local(settings, wav)
        if rec:
            return map_to_script(text, rec, duration), "whisper_local"
    return heuristic_alignment(text, wav), "heuristic"
