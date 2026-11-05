"""Automatic fixes for failing quality gates, applied by the preflight stage before rendering.

Fixes are small, targeted parameter changes stored per episode and read by the stage that owns
the problem (each stage hashes its own section, so only the affected stages re-run):

    autofix.json             {"screenplay": <hash>, "blocking": {...}, "performance": {...},
                              "audio": {...}, "captions": {...}, "history": [...]}
    shot_overrides.auto.json camera overrides (the user's shot_overrides.json always wins)

| gate               | fix                                                                       |
|--------------------|---------------------------------------------------------------------------|
| unrigged / t_pose  | fall back from the offending mocap clips to the built-in procedural clips  |
| foot_sliding       | stricter IK foot-lock contact detection for those characters               |
| interpenetration   | wider blocking (bodies) / larger hand-collision margin (hands)             |
| speaker_on_screen  | re-frame the shot on the speaker                                           |
| eyelines           | characters turn toward their partner earlier (lower turn threshold)        |
| static_shots       | slow push-in on the frozen shot                                            |
| lipsync_offset     | shift that character's mouth keys by the measured offset                   |
| clipping/loudness  | lower the limiter ceiling / re-normalize the master                        |
| captions           | smaller caption font so lines reflow inside the safe area                  |

Fixes are tied to the screenplay they were made for: when the script changes they are dropped
and re-derived, so a stale fix can never be applied to a different shot or line.
"""

from __future__ import annotations

import time

from storyforge.util.hashing import maybe_file_hash
from storyforge.util.io import read_json, write_json

FIXABLE = {"replan_performance", "disable_clips", "strict_foot_lock", "separate", "shot_override", "look_boost",
           "lipsync_shift", "relimit_mix", "renormalize_mix", "reflow_captions"}


def _script_hash(ctx) -> str | None:
    return maybe_file_hash(ctx.path("screenplay.final.json"))


def load_fixes(ctx) -> dict:
    doc = read_json(ctx.path("autofix.json"), {})
    return doc if doc and doc.get("screenplay") == _script_hash(ctx) else {}


def section(ctx, name: str) -> dict:
    return load_fixes(ctx).get(name, {}) or {}


def auto_overrides(ctx) -> dict:
    doc = read_json(ctx.path("shot_overrides.auto.json"), {})
    if not doc or doc.get("_screenplay") != _script_hash(ctx):
        return {}
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def merged_overrides(ctx) -> dict:
    """Auto overrides under the user's: per shot, user fields win."""
    user = read_json(ctx.path("shot_overrides.json"), {})
    out = {k: dict(v) for k, v in auto_overrides(ctx).items()}
    for sid, ov in user.items():
        out[sid] = {**out.get(sid, {}), **ov}
    return out


def apply_fixes(ctx, gates: list) -> list[dict]:
    """Record fixes for the failing gates; returns what was applied (empty = nothing new to try)."""
    doc = load_fixes(ctx) or {"screenplay": _script_hash(ctx)}
    perf = doc.setdefault("performance", {})
    blk = doc.setdefault("blocking", {})
    audio = doc.setdefault("audio", {})
    caps = doc.setdefault("captions", {})
    shot_auto = auto_overrides(ctx)
    user_ov = read_json(ctx.path("shot_overrides.json"), {})
    applied: list[dict] = []

    def note(gate, action, detail):
        applied.append({"gate": gate["name"], "action": action, "detail": detail})

    for g in gates:
        fix = g.get("fix") or {}
        a = fix.get("action")
        if a not in FIXABLE:
            continue
        if a == "disable_clips":
            have = set(perf.get("disable_mocap", []))
            new = {c for clips in fix.get("clips", {}).values() for c in clips} - have
            if new:
                perf["disable_mocap"] = sorted(have | new)
                note(g, a, f"built-in clips instead of {sorted(new)}")
            elif not perf.get("no_mocap"):
                perf["no_mocap"] = True
                note(g, a, "all mocap clips replaced by built-in clips")
        elif a == "replan_performance":
            if not perf.get("no_mocap"):
                perf["no_mocap"] = True
                note(g, a, "re-planned with built-in clips only")
        elif a == "strict_foot_lock":
            level = int(perf.get("foot_lock_level", 0))
            chars = sorted(set(perf.get("strict_foot_lock", [])) | set(fix.get("characters", [])))
            if level < 2 or chars != perf.get("strict_foot_lock"):
                perf["strict_foot_lock"] = chars
                perf["foot_lock_level"] = min(2, level + 1)
                note(g, a, f"foot lock level {perf['foot_lock_level']} for {chars}")
        elif a == "separate":
            if fix.get("pairs") and blk.get("spacing", 1.0) < 1.45:
                blk["spacing"] = round(min(1.45, blk.get("spacing", 1.0) * 1.12), 3)
                note(g, a, f"blocking spacing x{blk['spacing']}")
            if fix.get("hands") and perf.get("collision_margin", 1.0) < 2.0:
                perf["collision_margin"] = round(min(2.0, perf.get("collision_margin", 1.0) + 0.4), 2)
                note(g, a, f"hand collision margin x{perf['collision_margin']}")
        elif a == "shot_override":
            changed = []
            for sid, ov in (fix.get("overrides") or {}).items():
                if sid in user_ov:  # never fight the user's own shot choices
                    continue
                cur = shot_auto.get(sid, {})
                merged = {**cur, **ov}
                if merged != cur:
                    shot_auto[sid] = merged
                    changed.append(sid)
            if changed:
                note(g, a, f"shots {changed}: {[shot_auto[s] for s in changed]}")
        elif a == "look_boost":
            thr = float(blk.get("turn_threshold", 70.0))
            if thr > 35.0:
                blk["turn_threshold"] = max(35.0, thr - 20.0)
                note(g, a, f"turn toward partners beyond {blk['turn_threshold']:.0f} deg")
        elif a == "lipsync_shift":
            shifts = perf.setdefault("lipsync_shift", {})
            for cid, s in (fix.get("shift") or {}).items():
                shifts[cid] = int(round(shifts.get(cid, 0) + s))
            note(g, a, f"mouth keys shifted {shifts}")
        elif a in ("relimit_mix", "renormalize_mix"):
            ceiling = float(audio.get("ceiling_db", -1.5))
            if ceiling > -3.0:
                audio["ceiling_db"] = round(ceiling - 0.5, 2)
                note(g, a, f"limiter ceiling {audio['ceiling_db']} dBTP")
        elif a == "reflow_captions":
            scale = float(caps.get("scale", 1.0))
            if scale > 0.72:
                caps["scale"] = round(scale - 0.08, 2)
                note(g, a, f"caption font x{caps['scale']}")
    if applied:
        doc.setdefault("history", []).append({"t": round(time.time(), 1), "preset": ctx.options.preset,
                                              "applied": applied})
        write_json(ctx.path("autofix.json"), doc)
        write_json(ctx.path("shot_overrides.auto.json"), {"_screenplay": _script_hash(ctx), **shot_auto})
    return applied
