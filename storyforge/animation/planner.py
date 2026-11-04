"""Animation planning: timeline + blocking -> per-character NLA strips, squash keys and props.

Layers (bottom -> top, Blender NLA):
  base        idle loop (breathing, weight shifts, micro head motion), phase-offset per character
  locomotion  walk / run / tiptoe during blocking moves, playback speed matched to path speed
  gesture     scripted gestures + talk beats while speaking (+ M3 listener reactions)
  hold        arm pose while holding a prop
Blend-in/out on every strip; only bones a gesture actually moves are keyed so layers combine.
Exaggeration: gesture amplitude and squash & stretch scale with the beat intensity.
"""

from __future__ import annotations

import random
import re

from storyforge.animation.library import ClipLibrary
from storyforge_blender.proportions import body_metrics

FRAME_START = 1
TALK_VARIANTS = ["talk", "talk_both", "talk_left"]
GESTURE_PRIORITY = {"jump": 5, "cheer": 4, "gasp": 4, "recoil": 4, "pick_up": 5, "give": 4, "point": 3, "wave": 3}


def f_of(t: float, fps: int) -> float:
    return FRAME_START + t * fps


def plan_props(timeline: dict, blocking: dict) -> list[dict]:
    """Prop states over time: hidden / in a hand / resting at a world position."""
    props: dict[str, dict] = {}
    surfaces = blocking.get("surfaces", {})
    table = surfaces.get("table_top")
    for ev in timeline["events"]:
        if ev["type"] != "prop":
            continue
        pid = f"{ev['character']}_{ev['prop']}"
        p = props.setdefault(pid, {"id": pid, "type": ev["prop"], "owner": ev["character"], "events": []})
        p["events"].append(ev)
    out = []
    for p in props.values():
        evs = sorted(p["events"], key=lambda e: e["t"])
        owner = p["owner"]
        hx, hy, _ = blocking["home"].get(owner, [0, 0, 0])
        rest = [table[0] + (hx - table[0]) * 0.45, table[1] - 0.06, table[2] + 0.005] if table else [hx * 0.9, hy - 0.25, 0.0]
        first = evs[0]["action"]
        if first == "pick_up":
            # from the backpack if the character wears one (it "appears" in hand), else from the surface
            init = {"state": "hidden" if p["type"] in ("cup", "cookie", "gadget", "notebook", "flashlight") else "world",
                    "pos": rest}
        elif first in ("put_down", "hold", "use", "show", "give", "drop"):
            init = {"state": "hand", "character": owner, "hand": "R"}
        else:
            init = {"state": "world", "pos": rest}
        segs = [{"t": 0.0, **init}]
        holder = owner
        for ev in evs:
            a = ev["action"]
            t = ev["t"]
            if a == "pick_up":
                segs.append({"t": t + 0.55, "state": "hand", "character": holder, "hand": "R"})
            elif a == "put_down":
                pos = rest
                beat_action = next((b.get("action", "") for b in timeline["beats"] if b["id"] == ev.get("beat")), "")
                for other in props.values():
                    if other is p:
                        continue
                    if re.search(rf"\bon (the |a |his |her )?{re.escape(other['type'])}\b", beat_action.lower()):
                        o_rest = _resting_position(other, t, blocking)
                        if o_rest:
                            pos = [o_rest[0] + 0.02, o_rest[1] + 0.01, o_rest[2] + 0.006]
                segs.append({"t": t + 0.45, "state": "world", "pos": pos, "settle": True})
            elif a == "give" and ev.get("to"):
                segs.append({"t": t + 0.6, "state": "hand", "character": ev["to"], "hand": "R"})
                holder = ev["to"]
            elif a == "drop":
                segs.append({"t": t + 0.15, "state": "fall", "pos": [rest[0] + 0.35, rest[1] + 0.3, 0.0]})
            elif a in ("hold", "use", "show"):
                if segs[-1]["state"] != "hand":
                    segs.append({"t": t, "state": "hand", "character": holder, "hand": "R"})
        glow = []
        if p["type"] == "map":
            for b in timeline["beats"]:
                if b.get("beat_type") == "reveal" or "magic_shimmer" in (b.get("sfx") or []):
                    glow = [[b["start"], 0.0], [b["start"] + 0.8, 1.0], [timeline["duration"], 1.0]]
                    break
        light = []
        if p["type"] == "flashlight":
            on = True
            for ev in evs:
                if ev["action"] == "use":
                    # "use" toggles: the scripted beat in the sample has the light dying (flicker -> off)
                    t = ev["t"]
                    light = [[0.0, 1.0], [t + 0.2, 1.0], [t + 0.3, 0.2], [t + 0.38, 1.0], [t + 0.5, 0.1], [t + 0.6, 0.7],
                             [t + 0.75, 0.0]]
                    on = False
            if on:
                light = [[0.0, 1.0]]
        out.append({"id": p["id"], "type": p["type"], "owner": owner, "segments": segs, "glow": glow, "light": light})
    return _stow_conflicts(out)


def _stow_conflicts(props: list[dict]) -> list[dict]:
    """One prop per hand: when a character takes a new prop into a hand that is already holding one,
    the old prop is stowed (pocket/backpack) at that moment."""
    entries = []
    for p in props:
        for s in p["segments"]:
            if s["state"] == "hand":
                entries.append((s["t"], s.get("character"), s.get("hand", "R"), p["id"]))
    entries.sort()
    for t, ch, hand, pid in entries:
        for q in props:
            if q["id"] == pid:
                continue
            state = None
            for s in q["segments"]:
                if s["t"] <= t:
                    state = s
            if state and state["state"] == "hand" and state.get("character") == ch and state.get("hand", "R") == hand \
                    and state["t"] < t:
                q["segments"].append({"t": t, "state": "hidden", "stowed": True})
                q["segments"].sort(key=lambda s: s["t"])
    return props


def _resting_position(prop: dict, t: float, blocking: dict) -> list[float] | None:
    """Where a prop rests at time t (from its put_down events), if it is lying in the world."""
    surfaces = blocking.get("surfaces", {})
    table = surfaces.get("table_top")
    owner = prop["owner"]
    hx, hy, _ = blocking["home"].get(owner, [0, 0, 0])
    rest = [table[0] + (hx - table[0]) * 0.45, table[1] - 0.06, table[2] + 0.005] if table else [hx * 0.9, hy - 0.25, 0.0]
    state = None
    for ev in sorted(prop["events"], key=lambda e: e["t"]):
        if ev["t"] <= t:
            state = ev["action"]
    return rest if state in ("put_down", None) and any(e["action"] == "put_down" for e in prop["events"]) else None


def _active_bones(clip: dict, tol_deg: float = 1.5) -> list[str]:
    """Bones that actually move relative to the relaxed pose (so a gesture only overrides those)."""
    from storyforge.animation import quat as Q
    from storyforge.animation.procedural import RELAXED

    active = []
    for b, seq in clip["bones"].items():
        ref = RELAXED.get(b, Q.IDENTITY) if clip.get("source") == "procedural" else tuple(seq[0])
        if any(Q.angle_deg(Q.mul(tuple(q), Q.conj(ref))) > tol_deg for q in seq[:: max(1, len(seq) // 24)]):
            active.append(b)
    return active


def plan_character(cid: str, timeline: dict, blocking: dict, cast_entry: dict, lib: ClipLibrary,
                   props: list[dict], seed: int, extra_events: list[dict] | None = None) -> dict:
    fps = timeline["fps"]
    rng = random.Random(seed)
    settings = cast_entry.get("settings", {}) or {}
    gscale = float(settings.get("gesture_scale", 1.0))
    energy = float(settings.get("idle_energy", 0.6))
    metrics = body_metrics((cast_entry.get("look") or {}).get("body"))
    total_frames = timeline["frames"]
    strips: list[dict] = []
    used: set[str] = set()

    # base idle covering everything (+ margins), random phase so characters never breathe in sync
    idle = lib.get("idle")
    if idle:
        phase = rng.uniform(0, idle["frames"])
        start = FRAME_START - phase - fps
        reps = (total_frames + phase + 2 * fps) / idle["frames"] + 1
        strips.append({"clip": idle["name"], "track": "base", "start": round(start, 2), "repeat": round(reps, 3),
                       "scale": 1.0, "blend_in": 0, "blend_out": 0, "amplitude": round(0.6 + 0.8 * energy, 3),
                       "extrapolation": "HOLD"})
        used.add(idle["name"])

    # locomotion from blocking (speed matched to the path so feet don't slide)
    for lo in blocking.get("locomotion", []):
        if lo["character"] != cid or lo.get("distance", 0) < 0.05:
            continue
        kind = {"walk_to": "walk", "enter": "walk", "exit": "walk", "run_to": "run", "tiptoe_to": "tiptoe"}.get(lo["kind"], "walk")
        clip = lib.get(kind)
        if not clip:
            continue
        dur = max(0.4, lo["end"] - lo["start"])
        speed = lo["distance"] / dur
        stride_m = (clip.get("stride") or 1.2) * metrics["hip_z"]
        cycle_s = clip["frames"] / fps
        natural_speed = stride_m / cycle_s
        scale = max(0.55, min(1.8, natural_speed / max(1e-3, speed)))
        reps = dur * fps / (clip["frames"] * scale)
        strips.append({"clip": clip["name"], "track": "locomotion", "start": round(f_of(lo["start"], fps), 2),
                       "repeat": round(max(0.5, reps), 3), "scale": round(scale, 3), "blend_in": 5, "blend_out": 6,
                       "amplitude": 1.0, "extrapolation": "NOTHING"})
        used.add(clip["name"])

    # gestures
    holding = []  # (t0, t1) intervals with a prop in the right hand
    for p in props:
        segs = p["segments"]
        for i, s in enumerate(segs):
            if s["state"] == "hand" and s.get("character") == cid:
                t1 = segs[i + 1]["t"] if i + 1 < len(segs) else timeline["duration"]
                holding.append((s["t"], t1))
    occupied: list[tuple[float, float, int]] = []

    def free(t0: float, t1: float, prio: int) -> bool:
        return all(not (a < t1 and t0 < b) or prio > pr for a, b, pr in occupied)

    beats = {b["id"]: b for b in timeline["beats"]}
    gesture_events = [e for e in timeline["events"] + list(extra_events or [])
                      if e["type"] == "gesture" and e["character"] == cid]
    gesture_events.sort(key=lambda e: (e.get("reaction", False), e["t"]))  # scripted gestures claim time first
    for ev in gesture_events:
        clip = lib.get(ev["name"])
        if not clip:
            continue
        b = beats.get(ev["beat"], {})
        inten = float(ev.get("intensity", 0.5))
        dur_s = clip["frames"] / fps
        scale = 1.0 if ev["name"] not in TALK_VARIANTS else max(0.7, min(1.4, ev.get("duration", dur_s) / dur_s))
        if ev["name"] not in TALK_VARIANTS:
            scale *= 1.08 - 0.16 * inten  # intense beats play a bit snappier
        t0 = ev["t"]
        if ev["name"] == "pick_up":
            pe = next((e for e in timeline["events"] if e["type"] == "prop" and e["character"] == cid
                       and e.get("action") == "pick_up" and abs(e["t"] - ev["t"]) < 2.0), None)
            if pe:
                t0 = pe["t"] + 0.55 - 0.75 * scale  # the grab (0.75 s into the clip) lands on the prop pick-up
        prio = 1 if ev.get("reaction") else GESTURE_PRIORITY.get(ev["name"], 2)
        t1 = t0 + dur_s * scale
        if not free(t0, t1, prio):
            continue
        occupied.append((t0, t1, prio))
        amp = gscale * (0.8 + 0.45 * inten)
        strips.append({"clip": clip["name"], "track": "gesture", "start": round(f_of(max(0.0, t0), fps), 2),
                       "repeat": 1.0, "scale": round(scale, 3), "blend_in": 4, "blend_out": 7,
                       "amplitude": round(amp, 3), "extrapolation": "NOTHING", "bones": _active_bones(clip),
                       "beat": b.get("id")})
        used.add(clip["name"])
    # talk beats on spoken lines without an explicit gesture
    k = seed
    for b in timeline["beats"]:
        if b.get("speaker") != cid or not b.get("audio") or b.get("gesture"):
            continue
        a0, a1 = b["audio"]["start"], b["audio"]["end"]
        if a1 - a0 < 1.3 or float(b.get("intensity", 0.5)) < 0.3:
            continue
        in_hand = any(h0 <= a0 <= h1 for h0, h1 in holding)
        name = "talk_left" if in_hand else TALK_VARIANTS[k % len(TALK_VARIANTS)]
        k += 1
        clip = lib.get(name)
        if not clip:
            continue
        dur_s = clip["frames"] / fps
        scale = max(0.75, min(1.5, (a1 - a0 - 0.1) / dur_s))
        t0 = a0 + 0.05
        if not free(t0, t0 + dur_s * scale, 1):
            continue
        occupied.append((t0, t0 + dur_s * scale, 1))
        inten = float(b.get("intensity", 0.5))
        strips.append({"clip": clip["name"], "track": "gesture", "start": round(f_of(t0, fps), 2), "repeat": 1.0,
                       "scale": round(scale, 3), "blend_in": 5, "blend_out": 8,
                       "amplitude": round(gscale * (0.65 + 0.5 * inten), 3), "extrapolation": "NOTHING",
                       "bones": _active_bones(clip), "beat": b["id"]})
        used.add(clip["name"])
    # holding a prop: arm holding pose on its own track
    hold = lib.get("hold_item")
    for h0, h1 in holding:
        if hold and h1 - h0 > 0.3:
            strips.append({"clip": hold["name"], "track": "hold", "start": round(f_of(h0, fps), 2),
                           "repeat": round(max(0.3, (h1 - h0) * fps / hold["frames"]), 3), "scale": 1.0,
                           "blend_in": 6, "blend_out": 6, "amplitude": 1.0, "extrapolation": "NOTHING",
                           "bones": ["upper_arm.R", "forearm.R", "hand.R"]})
            used.add(hold["name"])
    # squash & stretch: from clips that author it + emphasis on intense surprised lines
    squash: list[list[float]] = []
    exag = float(settings.get("exaggeration", 1.0))
    for s in strips:
        clip = lib.get(s["clip"])
        if clip and clip.get("squash") and s["track"] == "gesture":
            for fr, val in clip["squash"]:
                squash.append([round(s["start"] + fr * s["scale"], 2), round(1 + (val - 1) * exag * min(1.4, s["amplitude"]), 4)])
    for b in timeline["beats"]:
        if b.get("speaker") == cid and b.get("emotion") in ("shocked", "excited") and float(b.get("intensity", 0)) >= 0.85:
            f0 = f_of(b["start"], fps)
            squash += [[round(f0 - 2, 2), 1.0], [round(f0 + 3, 2), round(1 + 0.045 * exag, 4)], [round(f0 + 9, 2), 0.99],
                       [round(f0 + 14, 2), 1.0]]
    squash.sort()
    return {"strips": strips, "squash": squash, "foot_lock": True, "secondary": True, "used_clips": sorted(used),
            "collision_fix": True, "hip_height": round(metrics["hip_z"], 4)}


def plan_performance(timeline: dict, blocking: dict, cast: dict, fps: int, log=print, use_mocap: bool = True) -> dict:
    lib = ClipLibrary(fps, use_mocap=use_mocap, log=log)
    from storyforge.performance.face import reaction_gestures

    props = plan_props(timeline, blocking)
    reactions = reaction_gestures(timeline)
    chars = {}
    used: set[str] = set()
    for i, cid in enumerate(timeline["cast"]):
        plan = plan_character(cid, timeline, blocking, cast.get(cid, {}), lib, props, seed=1000 + 37 * i,
                              extra_events=reactions)
        chars[cid] = plan
        used |= set(plan["used_clips"])
    clips = {}
    for name in used:
        c = lib.get(name)
        if c:
            clips[name] = {k: c[k] for k in ("name", "fps", "frames", "loop", "bones", "root", "root_normalized",
                                             "contacts", "category", "source") if k in c}
    return {"characters": chars, "props": props, "clips": clips, "library": lib.index(), "fps": fps,
            "mocap_used": sorted(n for n in used if n in lib.mocap)}


EXTRA_PALETTE = {
    "skin": ["#F2C39B", "#E8B48A", "#C68642", "#8D5A3B", "#F1D2B6", "#A0673D"],
    "top": ["#3D6B8C", "#C0392B", "#2E8B57", "#8E44AD", "#E67E22", "#16A085", "#D4AC0D", "#7F8C8D"],
    "bottom": ["#2C3E50", "#34495E", "#5D6D7E", "#6E2C00", "#1B2631"],
    "hair": ["#2E1A0F", "#4A3020", "#D9A441", "#1B1B1B", "#8B4513", "#5A3825"],
    "styles": ["short", "bob", "curly", "buzz", "ponytail", "bun", "long"],
}


def plan_extras(location: dict, timeline: dict, fps: int, seed: int = 4242, count: int | None = None) -> list[dict]:
    """Background extras for busy locations: simple looks walking along the back or idling."""
    if not location.get("extras"):
        return []
    rng = random.Random(seed)
    n = count if count is not None else rng.randint(3, 5)
    dur = timeline["duration"]
    extras = []
    for i in range(n):
        look = {"body": {"height": round(rng.uniform(0.9, 1.15), 2), "torso_width": round(rng.uniform(0.9, 1.2), 2)},
                "colors": {"skin": rng.choice(EXTRA_PALETTE["skin"]), "top": rng.choice(EXTRA_PALETTE["top"]),
                           "bottom": rng.choice(EXTRA_PALETTE["bottom"]), "hair": rng.choice(EXTRA_PALETTE["hair"]),
                           "shoes": "#2B2B2B"},
                "hair": {"style": rng.choice(EXTRA_PALETTE["styles"])}, "clothing": {"top": "tshirt"}}
        lane = location.get("extras_lane", [1.7, 2.6])
        xr = location.get("extras_x", [-5.5, 5.5])
        y = rng.uniform(lane[0], lane[1])
        walking = rng.random() < 0.7
        if walking:
            direction = rng.choice([-1, 1])
            x0 = xr[0] if direction > 0 else xr[1]
            speed = rng.uniform(0.7, 1.0)
            t_start = rng.uniform(-6.0, max(0.0, dur - 4.0))
            span = (xr[1] - xr[0]) / speed
            path = [[max(0.0, t_start), x0 + direction * speed * max(0.0, -t_start), y, 90 * direction],
                    [t_start + span, -x0, y, 90 * direction]]
            strips = [{"clip": "walk", "track": "locomotion", "start": FRAME_START + max(0.0, t_start) * fps,
                       "repeat": span * fps / 30 + 1, "scale": round(0.9 / speed, 3), "blend_in": 0, "blend_out": 0,
                       "amplitude": 1.0, "extrapolation": "HOLD"}]
        else:
            x = rng.uniform(xr[0] * 0.5, xr[1] * 0.5)
            path = [[0.0, x, y, rng.uniform(-60, 60)]]
            strips = [{"clip": "idle", "track": "base", "start": FRAME_START - rng.uniform(0, 150), "repeat": dur / 6 + 2,
                       "scale": 1.0, "blend_in": 0, "blend_out": 0, "amplitude": 1.0, "extrapolation": "HOLD"}]
        extras.append({"id": f"extra_{i}", "look": look, "path": path, "strips": strips,
                       "hip_height": round(body_metrics(look["body"])["hip_z"], 4)})
    return extras
