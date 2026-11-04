"""Compile the Blender scene spec (JSON) from the timeline, shot list, blocking and cast.

All decisions (timing, framing, performance curves, lighting) are made here in testable Python;
the Blender side only executes the spec. Times become frames as f = 1 + round(t * fps).
"""

from __future__ import annotations

from storyforge.cinematography.moves import camera_keys, focus_keys
from storyforge.lighting.three_point import base_lighting, shot_rig
from storyforge.performance.lipsync import cues_to_frames, frames_to_shape_keys, resolve_map
from storyforge.staging import head_point
from storyforge.util.hashing import stable_hash
from storyforge_blender.locations_data import get_location

FRAME_START = 1
SPEC_VERSION = 1


def t2f(t: float, fps: int) -> int:
    return FRAME_START + int(round(t * fps))


def mouth_tracks(timeline: dict, cid: str, face_cfg: dict | None, fps: int, shift: int = 0) -> dict:
    """Viseme shape-key keyframes for one character from the timed mouth cues of their lines
    (`shift` frames: quality auto-fix for a measured lip-sync offset)."""
    mapping = resolve_map(face_cfg)
    cues: list[dict] = []
    for b in timeline["beats"]:
        if b.get("speaker") != cid or not b.get("mouth"):
            continue
        cues.extend(b["mouth"])
    cues.sort(key=lambda c: c["start"])
    if not cues:
        return {}
    frame_cues = cues_to_frames(cues, 0.0, fps)
    for fc in frame_cues:
        fc["frame"] += FRAME_START + shift
        fc["end_frame"] += FRAME_START + shift
    tracks = frames_to_shape_keys(frame_cues, mapping, blend_frames=1)
    return {k: [[f, round(v, 4)] for f, v in vals] for k, vals in tracks.items()}


def compile_spec(*, episode_id: str, timeline: dict, shotlist: dict, blocking: dict, cast: dict, bible: dict,
                 style: str, grade: dict, preset: str, device: str, episode_dir: str, performance: dict | None = None,
                 audio_mix: str | None = "audio/mix.wav") -> dict:
    fps = timeline["fps"]
    frame_end = FRAME_START + max(1, timeline["frames"]) - 1
    loc_info = timeline.get("location_info") or {"preset": timeline["location"]}
    loc_preset = get_location(loc_info.get("preset", timeline["location"]))
    interior = loc_preset["kind"] == "interior"
    base = base_lighting(loc_preset, timeline["time_of_day"], interior)

    beats = {b["id"]: b for b in timeline["beats"]}
    shots_out, rigs = [], []
    for k, s in enumerate(shotlist["shots"]):
        ck = camera_keys(s, fps, FRAME_START, seed=k)
        fk = focus_keys(s, blocking, fps, FRAME_START, head_point, ck)
        f0 = t2f(s["start"], fps)
        f1 = max(f0, t2f(s["end"], fps) - 1)
        shots_out.append({"id": s["id"], "frame_start": f0, "frame_end": f1, "type": s["type"],
                          "lens_mm": s["lens_mm"], "fstop": s["fstop"], "camera_keys": ck, "focus_keys": fk,
                          "dof": True, "movement": s["movement"]["type"],
                          "interpolation": "LINEAR" if s["movement"]["type"] in ("handheld", "whip_pan") else "BEZIER",
                          "subject": s["subject"]})
        rigs.append({"frame": f0, "rig": shot_rig(s, beats.get(s["beat"]), base, loc_preset)})
    if shots_out:
        shots_out[-1]["frame_end"] = frame_end

    chars = []
    perf_doc = performance or {}
    perf = perf_doc.get("characters", {})
    for cid in timeline["cast"]:
        entry = cast.get(cid) or {"id": cid, "name": cid, "kind": "procedural", "look": {}}
        path = [[round(t, 4), round(x, 4), round(y, 4), round(yaw, 3)] for t, x, y, yaw in blocking["paths"][cid]]
        speaking = [[t2f(b["audio"]["start"], fps), t2f(b["audio"]["end"], fps)] for b in timeline["beats"]
                    if b.get("speaker") == cid and b.get("audio")]
        cperf = dict(perf.get(cid, {}))
        face_plan = cperf.pop("face", {}) or {}
        face = {"mouth": mouth_tracks(timeline, cid, (entry.get("rig") or {}).get("face"), fps,
                                      int((perf_doc.get("lipsync_shift") or {}).get(cid, 0)))}
        for name, keys in (face_plan.get("mouth_expr") or {}).items():
            face["mouth"][name] = keys
        for k in ("brows", "eyes", "blush", "look"):
            if face_plan.get(k):
                face[k] = face_plan[k]
        cperf.pop("used_clips", None)
        chars.append({"id": cid, "name": entry.get("name", cid), "kind": entry.get("kind", "procedural"),
                      "look": entry.get("look", {}), "rig": entry.get("rig", {}), "import": entry.get("import"),
                      "settings": entry.get("settings", {}), "path": path,
                      "performance": {"speaking_frames": speaking, **cperf}, "face": face})
    events = [{**e, "frame": t2f(e["t"], fps)} for e in timeline["events"]]
    return {
        "version": SPEC_VERSION,
        "episode_id": episode_id,
        "title": timeline.get("title"),
        "fps": fps,
        "frame_start": FRAME_START,
        "frame_end": frame_end,
        "duration": timeline["duration"],
        "style": {"preset": style, "lines": {"thickness": 3, "crease": 140}},
        "grade": grade,
        "render": {"preset": preset, "device": device},
        "location": {"preset": loc_preset["preset"], "time_of_day": timeline["time_of_day"], "seed": 11},
        "lighting": {"base": base, "rigs": rigs},
        "characters": chars,
        "shots": shots_out,
        "events": events,
        "clips": perf_doc.get("clips", {}),
        "clips_hash": stable_hash(perf_doc.get("clips", {})),
        "props": perf_doc.get("props", []),
        "extras": perf_doc.get("extras", []),
        "fx": perf_doc.get("fx", []),
        "audio": {"mix": audio_mix},
        "paths": {"episode_dir": episode_dir},
    }


def shot_fingerprint(spec: dict, shot_id: str) -> dict:
    """What a shot's pixels depend on: global look + this shot + everything animated in its range.

    Used as the per-shot render cache key so editing one shot (or one beat) only re-renders the
    shots whose frames actually change."""
    shot = next(s for s in spec["shots"] if s["id"] == shot_id)
    f0, f1 = shot["frame_start"], shot["frame_end"]
    margin = spec["fps"]  # one second of context (motion blur, eased curves, secondary motion)
    lo, hi = f0 - margin, f1 + margin // 2

    def window(keys):
        if isinstance(keys, list):
            out = [k for k in keys if isinstance(k, (list, tuple)) and lo <= k[0] <= hi]
            before = [k for k in keys if isinstance(k, (list, tuple)) and k[0] < lo]
            return (before[-1:] + out) if before else out
        if isinstance(keys, dict):
            return {kk: window(v) for kk, v in keys.items()}
        return keys

    chars = []
    for c in spec["characters"]:
        perf = dict(c["performance"])
        strips = []
        for st in perf.pop("strips", []):
            frames = (spec.get("clips", {}).get(st["clip"]) or {}).get("frames", 60)
            end = st["start"] + frames * st.get("scale", 1.0) * st.get("repeat", 1.0)
            if st["start"] <= hi + margin and end >= lo - margin:
                strips.append(st)
        chars.append({"id": c["id"], "look": c["look"], "rig": c["rig"], "import": c.get("import"),
                      "path": [p for p in c["path"]], "face": window(c["face"]), "strips": strips,
                      "performance": window(perf)})
    rig = next((r for r in spec["lighting"]["rigs"] if r["frame"] == f0), None)
    return {
        "shot": shot, "style": spec["style"], "grade": spec["grade"], "render": spec["render"],
        "location": spec["location"], "lighting_base": spec["lighting"]["base"], "rig": rig, "fps": spec["fps"],
        "characters": chars,
        "events": [e for e in spec["events"] if lo - spec["fps"] * 2 <= e["frame"] <= hi],
        "clips_hash": spec.get("clips_hash"),
        "props": spec.get("props", []),
        "extras": spec.get("extras", []),
        "fx": [x for x in spec.get("fx", []) if lo - margin <= x.get("frame", 0) <= hi + margin],
    }
