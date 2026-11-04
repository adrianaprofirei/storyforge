"""Timeline builder: screenplay beats + voice durations -> timed beats and events.

Pacing is rule-based editorial timing for shorts: the hook starts ~0.1 s in, gaps between
speakers are tight (0.12-0.35 s), jokes get a beat before the punchline, interrupted lines
overlap, silent action beats get durations from their content, and the last beat holds so a
cliffhanger can breathe. Word timings and mouth cues are shifted to absolute time.
"""

from __future__ import annotations

import math
import re

from storyforge.util.text import ends_interrupted, estimate_speech_seconds, is_question

LEAD_IN = 0.12


def gap_after(beat: dict, nxt: dict | None) -> float:
    if nxt is None:
        return 0.0
    line, nline = (beat.get("line") or ""), (nxt.get("line") or "")
    if line and ends_interrupted(line) and nline:
        return -0.12  # the next speaker cuts in
    if not line or not nline:
        return 0.1
    if beat.get("speaker") == nxt.get("speaker"):
        return 0.14
    gap = 0.22
    if nxt.get("beat_type") in ("joke", "payoff"):
        gap = 0.34  # comic beat before the punchline
    elif is_question(line):
        gap = 0.18
    if nxt.get("beat_type") in ("cliffhanger", "reveal"):
        gap = 0.45
    if (nxt.get("delivery") or {}).get("pace") == "fast" and nxt.get("intensity", 0.5) > 0.7:
        gap = min(gap, 0.16)
    return gap


def silent_beat_duration(beat: dict) -> float:
    d = 1.25 + 0.45 * float(beat.get("intensity", 0.5))
    bt = beat.get("beat_type")
    if bt == "reveal":
        d += 0.45
    elif bt in ("cliffhanger", "payoff"):
        d += 0.7
    sfx = " ".join(beat.get("sfx") or [])
    if "chime" in sfx:
        d = max(d, 2.3)
    if beat.get("motion"):
        d = max(d, 2.2)
    words = len(re.findall(r"\w+", beat.get("action", "")))
    d += min(0.6, max(0.0, (words - 12) * 0.03))
    return round(min(d, 3.4), 3)


def tail_hold(beat: dict, finale: bool) -> float:
    if finale:
        return 1.6
    return 1.3 if beat.get("beat_type") == "cliffhanger" else 0.9


def infer_actor(beat: dict, cast: list[str], names: dict[str, str]) -> str | None:
    if beat.get("speaker"):
        return beat["speaker"]
    for p in beat.get("props") or []:
        return p.get("character")
    for fx in beat.get("fx") or []:
        return fx.get("character")
    mo = beat.get("motion") or {}
    if mo.get("character"):
        return mo["character"]
    text = (beat.get("action") or "").lower()
    best, pos = None, 10 ** 9
    for cid in cast:
        for token in {cid.lower(), names.get(cid, cid).lower()}:
            m = re.search(rf"\b{re.escape(token)}\b", text)
            if m and m.start() < pos:
                best, pos = cid, m.start()
    return best


def build_timeline(sp: dict, voices: dict, lipsync: dict, fps: int, bible: dict, is_finale: bool,
                   duration_limit: float | None = None) -> dict:
    names = {c["id"]: c.get("name", c["id"]) for c in bible.get("characters", [])}
    cast = sp["cast"]
    beats_out, events = [], []
    t = LEAD_IN
    beats = sp["beats"]
    for i, b in enumerate(beats):
        nxt = beats[i + 1] if i + 1 < len(beats) else None
        vline = voices.get("lines", {}).get(b["id"])
        actor = infer_actor(b, cast, names)
        entry = {k: b.get(k) for k in ("id", "speaker", "addressee", "line", "emotion", "intensity", "action",
                                       "performance_note", "camera_hint", "beat_type", "gesture", "motion",
                                       "props", "fx", "sfx", "delivery")}
        entry["actor"] = actor
        start = t
        if vline:
            dur = float(vline["duration"])
            entry["audio"] = {"file": vline["file"], "start": round(start, 4), "end": round(start + dur, 4),
                              "duration": dur, "silent": bool(vline.get("silent"))}
            entry["words"] = [{"word": w["word"], "start": round(start + w["start"], 4),
                               "end": round(start + w["end"], 4)} for w in vline["words"]]
            cues = (lipsync.get("lines", {}).get(b["id"]) or {}).get("cues", [])
            entry["mouth"] = [{"start": round(start + c["start"], 4), "end": round(start + c["end"], 4),
                               "shape": c["shape"]} for c in cues]
            end = start + dur
            # long actions under a short line get a little extra screen time
            act_need = 0.9 if (b.get("gesture") in ("jump", "cheer", "pick_up", "give")) else 0.0
            end = max(end, start + act_need)
        elif b.get("line"):
            dur = estimate_speech_seconds(b["line"], (b.get("delivery") or {}).get("pace", "normal"), b.get("emotion"))
            entry["audio"] = None
            entry["words"] = []
            entry["mouth"] = []
            end = start + dur
        else:
            entry["audio"] = None
            entry["words"] = []
            entry["mouth"] = []
            end = start + silent_beat_duration(b)
        entry["start"], entry["end"] = round(start, 4), round(end, 4)
        beats_out.append(entry)
        # ---- events derived from the beat (performance layers consume these)
        if b.get("gesture") and actor:
            lead = 0.12 if b.get("line") else 0.0  # gesture starts just before the line (anticipation)
            events.append({"t": round(max(0.0, start - lead), 4), "type": "gesture", "character": actor,
                           "name": b["gesture"], "intensity": b.get("intensity", 0.5), "beat": b["id"],
                           "duration": round(min(max(1.0, end - start), 3.0), 3)})
        for k, p in enumerate(b.get("props") or []):
            events.append({"t": round(start + 0.1 + 0.25 * k, 4), "type": "prop", "character": p["character"],
                           "prop": p["prop"], "action": p["action"], "to": p.get("to"), "beat": b["id"]})
        for fx in b.get("fx") or []:
            events.append({"t": round(start + 0.15, 4), "type": "fx", "character": fx["character"], "fx": fx["type"],
                           "duration": round(max(1.0, min(2.6, end - start + 0.4)), 3), "beat": b["id"],
                           "intensity": b.get("intensity", 0.5)})
        for tag in b.get("sfx") or []:
            events.append({"t": round(start + (0.05 if not b.get("line") else 0.0), 4), "type": "sfx", "tag": tag,
                           "beat": b["id"], "character": actor})
        if b.get("motion"):
            mo = dict(b["motion"])
            who = [mo["character"]] if mo.get("character") else (cast if mo["type"] in ("tiptoe_to", "walk_to")
                                                               and not actor else [actor or cast[0]])
            for cid in who:
                events.append({"t": round(start, 4), "type": "motion", "character": cid, "motion": mo["type"],
                               "to": mo.get("to"), "side": mo.get("side"), "duration": round(end - start, 3),
                               "beat": b["id"]})
        t = end + gap_after(b, nxt)
        if duration_limit and t >= duration_limit:
            break
    duration = (beats_out[-1]["end"] if beats_out else 1.0) + tail_hold(beats_out[-1] if beats_out else {}, is_finale)
    if duration_limit:
        duration = min(duration, duration_limit)
        beats_out = [b for b in beats_out if b["start"] < duration]
        for b in beats_out:
            b["end"] = min(b["end"], duration)
        events = [e for e in events if e["t"] < duration]
    events.sort(key=lambda e: (e["t"], e["type"]))
    frames = int(math.ceil(duration * fps))
    return {"version": 1, "fps": fps, "duration": round(duration, 4), "frames": frames,
            "title": sp.get("title"), "cast": cast, "location": sp["location"], "time_of_day": sp["time_of_day"],
            "music_mood": sp.get("music_mood"), "part": sp.get("part", 1), "is_finale": is_finale,
            "beats": beats_out, "events": events}


def beat_at(timeline: dict, t: float) -> dict | None:
    for b in timeline["beats"]:
        if b["start"] <= t < b["end"]:
            return b
    return None


def speaking_intervals(timeline: dict) -> list[tuple[float, float, str]]:
    return [(b["audio"]["start"], b["audio"]["end"], b["speaker"]) for b in timeline["beats"]
            if b.get("audio") and b.get("speaker")]
