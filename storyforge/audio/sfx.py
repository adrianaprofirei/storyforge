"""Automatic sound design: foley/SFX cues and the music plan from the timeline + performance.

Cue sources:
* scripted `sfx` tags on beats (the writer's intent wins),
* footsteps on the location's surface at the exact foot plants of locomotion clips (from the NLA
  plan: strip start, playback scale, repetitions and the clip's contact frames),
* gestures (jump landing thud + take-off whoosh, claps, cloth on big arm moves, pick-ups),
* props (map rustle/slam, cup clink, cookie tap + roll, key jingle/turn, flashlight clicks, gadget),
* camera (whoosh on whip pans and snap zooms),
* emotion FX (twinkle, pops) and, in the cartoon style, cartoon accents (boing, zip, pop),
* ambience beds for exteriors / crowds.
Music: a mood-matched bed with fades, stings on reveals / cliffhangers / payoffs, a pull-out right
before the cliffhanger sting, and a swell under the finale payoff.
"""

from __future__ import annotations

import random

from storyforge_blender.locations_data import get_location

TAG_ALIASES = {"magic": "magic_shimmer", "chime": "clock_chime", "bell": "clock_chime", "beep": "gadget_beep",
               "zip": "backpack_zip", "creak": "floor_creak", "slam": "paper_slam", "whoosh": "whoosh",
               "sting": "reveal_sting", "click": "flashlight_click", "keys": "key_jingle"}
MUSIC_TAGS = ("sting",)
GESTURE_SFX = {
    "clap": [(0.4, "clap", -8), (0.7, "clap", -8), (1.0, "clap", -8)],
    "cheer": [(0.3, "cloth", -10)], "recoil": [(0.1, "cloth", -9)], "gasp": [(0.12, "cloth", -12)],
    "facepalm": [(0.33, "impact_soft", -18)], "give": [(0.3, "cloth", -14)], "pick_up": [(0.45, "cloth", -12)],
    "wave": [(0.3, "cloth", -18)], "point": [(0.32, "cloth", -16)], "shrug": [(0.25, "cloth", -16)],
    "hands_on_hips": [(0.3, "cloth", -14)], "cross_arms": [(0.35, "cloth", -15)], "thumbs_up": [(0.28, "cloth", -17)],
}
PROP_SFX = {
    ("map", "put_down"): [(0.45, "paper_slam", -6)], ("map", "pick_up"): [(0.5, "paper", -12)],
    ("map", "show"): [(0.1, "paper", -14)], ("cup", "put_down"): [(0.45, "clink", -10)],
    ("cup", "pick_up"): [(0.55, "clink", -16)], ("cookie", "drop"): [(0.45, "tap", -10), (0.6, "roll", -10)],
    ("key", "pick_up"): [(0.55, "key_jingle", -8)], ("key", "use"): [(0.2, "key_turn", -6)],
    ("flashlight", "use"): [(0.2, "flashlight_click", -10), (0.5, "flashlight_click", -12), (0.75, "flashlight_click", -10)],
    ("gadget", "show"): [(0.15, "gadget_beep", -12)], ("gadget", "use"): [(0.15, "gadget_beep", -12)],
    ("notebook", "pick_up"): [(0.5, "paper", -16)], ("book", "put_down"): [(0.45, "tap", -10)],
}
FX_SFX = {"lightbulb": ("twinkle", -12), "sparkles": ("twinkle", -14), "question_mark": ("pop", -16),
          "exclamation_mark": ("pop", -12), "shock_lines": ("whoosh+fast", -14)}
CARTOON_FX = {"question_mark": ("boing", -14), "exclamation_mark": ("zip", -12), "sweat_drop": ("pop", -18),
              "anger_mark": ("pop", -14)}


def _norm_tag(tag: str) -> str:
    t = tag.lower().strip()
    return TAG_ALIASES.get(t, t)


def plan_sfx(timeline: dict, shotlist: dict, performance: dict, blocking: dict, style: str) -> list[dict]:
    rng = random.Random(42)
    fps = timeline["fps"]
    loc = get_location((timeline.get("location_info") or {}).get("preset", timeline["location"]))
    surface = (timeline.get("location_info") or {}).get("surface") or loc.get("surface", "wood")
    cues: list[dict] = []
    scripted_beats: dict[str, list[float]] = {}

    def pan_of(cid):
        if cid and cid in blocking.get("home", {}):
            return max(-0.35, min(0.35, blocking["home"][cid][0] / 2.5))
        return 0.0

    def add(t, tag, gain_db, cid=None, source="auto", bus="sfx"):
        if t < 0 or t > timeline["duration"]:
            return
        cues.append({"t": round(t, 4), "tag": tag, "gain_db": gain_db, "pan": pan_of(cid), "character": cid,
                     "source": source, "bus": bus})

    # 1) scripted tags
    for b in timeline["beats"]:
        for tag in b.get("sfx") or []:
            nt = _norm_tag(tag)
            t = b["start"] + (0.0 if not b.get("line") else 0.05)
            bus = "music" if any(m in nt for m in MUSIC_TAGS) else "sfx"
            gain = -4 if "chime" in nt else (-6 if bus == "music" else -8)
            add(t, nt, gain, b.get("actor"), "script", bus)
            scripted_beats.setdefault(b["id"], []).append(t)

    def near_scripted(beat_id, t, window=0.6):
        return any(abs(t - s) < window for s in scripted_beats.get(beat_id, []))

    # 2) footsteps from locomotion strips (exact foot plants)
    clips = performance.get("clips", {})
    for cid, plan in performance.get("characters", {}).items():
        for st in plan.get("strips", []):
            if st["track"] != "locomotion":
                continue
            clip = clips.get(st["clip"])
            if not clip:
                continue
            frames = clip["frames"]
            plants = sorted({c[0] for spans in clip.get("contacts", {}).values() for c in spans})
            reps = int(st.get("repeat", 1)) + 1
            soft = st["clip"] in ("tiptoe",)
            for r in range(reps):
                for c in plants:
                    f = st["start"] + (r * frames + c) * st.get("scale", 1.0)
                    end = st["start"] + frames * st.get("scale", 1.0) * st.get("repeat", 1.0)
                    if f > end:
                        continue
                    add((f - 1) / fps, f"footstep+{surface}", (-17 if soft else -11) + rng.uniform(-1.5, 1.5), cid)
    # 3) gestures
    for cid, plan in performance.get("characters", {}).items():
        for st in plan.get("strips", []):
            if st["track"] != "gesture":
                continue
            t0 = (st["start"] - 1) / fps
            sc = st.get("scale", 1.0)
            name = st["clip"]
            if name == "jump":
                add(t0 + 0.42 * sc, "whoosh+fast", -14, cid)
                add(t0 + 0.8 * sc, "impact_soft", -6, cid)
                add(t0 + 0.8 * sc, f"footstep+{surface}", -8, cid)
                if style == "cartoon":
                    add(t0 + 0.8 * sc, "boing", -12, cid)
            for at, tag, g in GESTURE_SFX.get(name, []):
                t = t0 + at * sc
                if not near_scripted(st.get("beat"), t, 0.3):
                    add(t, tag, g, cid)
    # 4) props
    for ev in timeline["events"]:
        if ev["type"] != "prop":
            continue
        for at, tag, g in PROP_SFX.get((ev["prop"], ev["action"]), []):
            t = ev["t"] + at
            if not near_scripted(ev.get("beat"), t):
                add(t, tag, g, ev["character"])
    # 5) camera moves
    for s in shotlist.get("shots", []):
        mv = s.get("movement", {}).get("type")
        if mv == "whip_pan":
            add(s["start"] - 0.05, "whoosh", -9)
        elif mv == "snap_zoom":
            add(s["start"], "whoosh+fast", -12)
            if style == "cartoon":
                add(s["start"], "zip", -16)
    # 6) emotion FX
    for fx in performance.get("fx", []):
        t = (fx["frame"] - 1) / fps
        if fx["type"] in FX_SFX:
            tag, g = FX_SFX[fx["type"]]
            add(t, tag, g, fx["character"])
        if style == "cartoon" and fx["type"] in CARTOON_FX:
            tag, g = CARTOON_FX[fx["type"]]
            add(t, tag, g, fx["character"])
    cues.sort(key=lambda c: c["t"])
    return cues


def plan_ambience(timeline: dict, performance: dict) -> list[dict]:
    loc = get_location((timeline.get("location_info") or {}).get("preset", timeline["location"]))
    out = []
    if loc.get("kind") == "exterior":
        out.append({"tag": "ambience+outdoors", "gain_db": -26})
    if performance.get("extras"):
        out.append({"tag": "ambience+crowd", "gain_db": -30})
    return out


def plan_music(timeline: dict, is_finale: bool, sfx_cues: list[dict]) -> dict:
    mood = timeline.get("music_mood") or "playful"
    beats = timeline["beats"]
    stings = []
    scripted_music = [c for c in sfx_cues if c["bus"] == "music"]
    for b in beats:
        if any(abs(c["t"] - b["start"]) < 0.7 for c in scripted_music):
            continue
        if b.get("beat_type") == "reveal":
            stings.append({"t": b["start"], "tag": "reveal_sting", "gain_db": -8})
    cliff = next((b for b in beats if b.get("beat_type") == "cliffhanger"), None) if not is_finale else None
    pull_out = None
    if cliff:
        stings.append({"t": cliff["start"], "tag": "cliffhanger_sting", "gain_db": -5})
        pull_out = max(0.0, cliff["start"] - 0.5)
    swell = None
    if is_finale:
        pay = [b for b in beats if b.get("beat_type") == "payoff" and not b.get("speaker")]
        if pay:
            top = max(pay, key=lambda b: float(b.get("intensity", 0)))
            if not any(abs(c["t"] - top["start"]) < 0.7 for c in scripted_music):
                stings.append({"t": top["start"], "tag": "payoff_sting", "gain_db": -6})
            swell = top["start"]
    return {"mood": mood, "start": 0.0, "end": timeline["duration"], "fade_in": 0.4, "fade_out": 1.2,
            "pull_out": pull_out, "swell": swell, "stings": stings, "bed_gain_db": -19.0}
