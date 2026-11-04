"""Animation quality gates, computed from the post-build scene analysis (scene/analysis.json).

The analysis samples every 2nd frame of every shot inside Blender: head/hand/foot/hip/chest world
positions, the head's facing direction, the head's box in the shot camera, arm elevation and the
camera transform. From it we check, per the series' quality bar:

* unrigged characters and T-poses (both arms horizontal for >= 0.5 s while on screen),
* foot sliding (a planted foot drifting > 5 cm),
* interpenetration (hands inside the torso, two bodies overlapping),
* the speaker off screen for most of their line (reaction shots and inserts excepted),
* eyelines (the speaker's head turned away from the addressee, listeners not looking at the speaker),
* static shots (no camera and no character motion for > 1.5 s),
* lip-sync offset (mouth openness vs the dialogue envelope, cross-correlated: > 1 frame fails).

Every failing gate carries a `fix` the preflight stage can apply automatically (see autofix.py).
"""

from __future__ import annotations

import math

import numpy as np

from storyforge.quality.gates import Gate
from storyforge.util.io import read_json

TPOSE_DEG = 15.0
TPOSE_MIN_S = 0.5
SLIDE_WARN_M = 0.05
SLIDE_FAIL_M = 0.10
STATIC_MAX_S = 1.5
EYELINE_SPEAKER_DEG = 45.0
EYELINE_LISTENER_DEG = 55.0


def _visible(box, min_inside: float = 0.4) -> bool:
    if not box:
        return False
    x0, y0, x1, y1 = box
    w, h = max(1e-6, x1 - x0), max(1e-6, y1 - y0)
    ix = max(0.0, min(1.0, x1) - max(0.0, x0))
    iy = max(0.0, min(1.0, y1) - max(0.0, y0))
    return ix * iy / (w * h) >= min_inside


def _time(frame: int, fps: int) -> float:
    return (frame - 1) / fps


def _all_samples(an: dict):
    for shot in an.get("shots", []):
        for smp in shot.get("samples", []):
            yield shot, smp


def _runs(flags: list[tuple[int, bool, str]], min_len_frames: int) -> list[tuple[int, int, str]]:
    """[(frame, flag, shot)] sorted by frame -> runs of True spanning >= min_len_frames."""
    out, start, shot = [], None, None
    last = None
    for f, on, sid in flags + [(10 ** 9, False, "")]:
        if on and start is None:
            start, shot = f, sid
        elif not on and start is not None:
            if last - start >= min_len_frames:
                out.append((start, last, shot))
            start = None
        last = f
    return out


def _active_clips(perf: dict, cid: str, frame: int) -> list[str]:
    out = []
    clips = perf.get("clips", {})
    for st in (perf.get("characters", {}).get(cid, {}) or {}).get("strips", []):
        clip = clips.get(st["clip"])
        if not clip:
            continue
        length = clip["frames"] * st.get("scale", 1.0) * st.get("repeat", 1.0)
        if st["start"] <= frame <= st["start"] + length:
            out.append(st["clip"])
    return out


# ------------------------------------------------------------------ gates
def gate_rig(an: dict) -> Gate:
    bad = [cid for cid, c in an.get("characters", {}).items() if not c.get("has_animation")]
    if bad:
        return Gate("unrigged", "fail", f"{len(bad)} character(s) without animation: {', '.join(bad)}",
                    [{"character": c} for c in bad], {"action": "replan_performance", "characters": bad})
    return Gate("unrigged", "pass", f"all {len(an.get('characters', {}))} characters are rigged and animated")


def gate_tpose(an: dict, perf: dict) -> Gate:
    fps = an["fps"]
    issues = []
    for cid in an.get("characters", {}):
        flags = []
        for shot, smp in _all_samples(an):
            d = smp["chars"].get(cid) or {}
            el = d.get("arm_elev") or [None, None]
            on = (el[0] is not None and el[1] is not None and abs(el[0]) < TPOSE_DEG and abs(el[1]) < TPOSE_DEG
                  and _visible(d.get("head_screen"), 0.2))
            flags.append((smp["frame"], on, shot["id"]))
        flags.sort()
        for a, b, sid in _runs(flags, int(TPOSE_MIN_S * fps)):
            issues.append({"character": cid, "shot": sid, "frames": [a, b],
                           "clips": _active_clips(perf, cid, (a + b) // 2)})
    if issues:
        disable: dict[str, list[str]] = {}
        for i in issues:
            disable.setdefault(i["character"], [])
            disable[i["character"]] += [c for c in i["clips"] if c not in disable[i["character"]]]
        return Gate("t_pose", "fail", f"{len(issues)} T-pose span(s) on screen", issues,
                    {"action": "disable_clips", "clips": disable})
    return Gate("t_pose", "pass", "no T-poses on screen")


def planned_contacts(perf: dict, cid: str, n_frames: int) -> dict[str, np.ndarray]:
    """Frames where each foot is meant to be planted, from the NLA plan: standing (base/idle) feet are
    planted; during locomotion only the core of each clip contact span counts; jumps and strip blends
    are unknown (not checked)."""
    n = n_frames + 2
    mask = {f: np.ones(n, dtype=bool) for f in ("foot.L", "foot.R")}
    unknown = np.zeros(n, dtype=bool)
    clips = perf.get("clips", {})
    for st in (perf.get("characters", {}).get(cid, {}) or {}).get("strips", []):
        clip = clips.get(st["clip"])
        if not clip:
            continue
        start, scale, rep, frames = float(st["start"]), float(st.get("scale", 1.0)), float(st.get("repeat", 1.0)), clip["frames"]
        end = start + frames * scale * rep
        lo, hi = max(0, int(math.floor(start))), min(n - 1, int(math.ceil(end)))
        if hi <= 0 or lo >= n - 1:
            continue
        if st["track"] == "locomotion":
            for foot in mask:
                mask[foot][lo:hi + 1] = False
            for foot, spans in (clip.get("contacts") or {}).items():
                if foot not in mask:
                    continue
                for r in range(int(rep) + 1):
                    for a, b in spans:
                        fa, fb = start + (r * frames + a) * scale, start + (r * frames + b) * scale
                        shrink = (fb - fa) * 0.2
                        fa, fb = fa + shrink, min(end, fb - shrink)
                        if fa >= fb:
                            continue
                        mask[foot][max(lo, int(math.ceil(fa))):min(hi, int(math.floor(fb))) + 1] = True
            pad = 6
            unknown[lo:min(n, lo + int(st.get("blend_in", 0)) + pad)] = True
            unknown[max(0, hi - int(st.get("blend_out", 0)) - pad):hi + 1] = True
        elif st["track"] == "gesture" and st["clip"] in ("jump",):
            unknown[lo:hi + 1] = True
    return {f: m & ~unknown for f, m in mask.items()}


def gate_foot_sliding(an: dict, perf: dict) -> Gate:
    issues = []
    worst = 0.0
    n_frames = max((s["frame_end"] for s in an.get("shots", [])), default=0)
    for cid in an.get("characters", {}):
        planted = planned_contacts(perf, cid, n_frames)
        samples = sorted(((smp["frame"], smp["chars"].get(cid) or {}, shot["id"]) for shot, smp in _all_samples(an)),
                         key=lambda x: x[0])
        for foot, mask in planted.items():
            run: list[tuple[int, list, str]] = []
            for f, d, sid in samples + [(None, {}, "")]:
                on = (f is not None and f < len(mask) and bool(mask[f]) and d.get(foot) is not None
                      and _visible(d.get("head_screen"), 0.2))
                if on:
                    run.append((f, d[foot], sid))
                    continue
                if len(run) >= 3:
                    # typical drift = median foot speed over the planted span x its duration: robust to the
                    # plan's contact labels being a few frames early/late (heel strike, toe off)
                    fps = an["fps"]
                    speeds = [math.dist(a[1][:2], b[1][:2]) * fps / max(1, b[0] - a[0])
                              for a, b in zip(run, run[1:], strict=False)]
                    slide = float(np.median(speeds)) * (run[-1][0] - run[0][0]) / fps
                    if slide > SLIDE_WARN_M:
                        issues.append({"character": cid, "shot": run[0][2], "foot": foot,
                                       "frames": [run[0][0], run[-1][0]], "slide_m": round(slide, 3)})
                        worst = max(worst, slide)
                run = []
    if issues:
        status = "fail" if worst > SLIDE_FAIL_M else "warn"
        return Gate("foot_sliding", status, f"{len(issues)} planted foot drift(s), worst {worst * 100:.1f} cm",
                    issues, {"action": "strict_foot_lock", "characters": sorted({i["character"] for i in issues})})
    return Gate("foot_sliding", "pass", "planted feet stay put (< 5 cm drift)")


def _seg_dist(p, a, b) -> float:
    p, a, b = np.asarray(p), np.asarray(a), np.asarray(b)
    ab = b - a
    t = float(np.clip(np.dot(p - a, ab) / max(1e-9, float(np.dot(ab, ab))), 0.0, 1.0))
    return float(np.linalg.norm(p - (a + t * ab)))


def gate_interpenetration(an: dict) -> Gate:
    fps = an["fps"]
    chars = an.get("characters", {})
    issues = []
    # hands inside the own torso
    for cid, meta in chars.items():
        radius = min(meta["torso_w"], meta["torso_d"]) / 2 * 0.7
        flags = []
        for shot, smp in _all_samples(an):
            d = smp["chars"].get(cid) or {}
            on = False
            if d.get("hips") and d.get("chest") and _visible(d.get("head_screen"), 0.2):
                for h in ("hand.L", "hand.R"):
                    if d.get(h) and _seg_dist(d[h], d["hips"], d["chest"]) < radius:
                        on = True
            flags.append((smp["frame"], on, shot["id"]))
        flags.sort()
        for a, b, sid in _runs(flags, int(0.3 * fps)):
            issues.append({"type": "hand_in_torso", "character": cid, "shot": sid, "frames": [a, b]})
    # bodies overlapping
    ids = sorted(chars)
    pairs_bad = set()
    for i, ca in enumerate(ids):
        for cb in ids[i + 1:]:
            ra = max(chars[ca]["torso_w"], chars[ca]["torso_d"]) / 2
            rb = max(chars[cb]["torso_w"], chars[cb]["torso_d"]) / 2
            flags = []
            for shot, smp in _all_samples(an):
                a, b = smp["chars"].get(ca, {}), smp["chars"].get(cb, {})
                on = bool(a.get("hips") and b.get("hips")) and math.dist(a["hips"][:2], b["hips"][:2]) < (ra + rb) * 0.85
                flags.append((smp["frame"], on, shot["id"]))
            flags.sort()
            for s0, s1, sid in _runs(flags, int(0.2 * fps)):
                issues.append({"type": "bodies_overlap", "characters": [ca, cb], "shot": sid, "frames": [s0, s1]})
                pairs_bad.add((ca, cb))
    if issues:
        fix = {"action": "separate", "pairs": sorted(pairs_bad),
               "hands": sorted({i["character"] for i in issues if i["type"] == "hand_in_torso"})}
        return Gate("interpenetration", "fail", f"{len(issues)} interpenetration span(s)", issues, fix)
    return Gate("interpenetration", "pass", "no hands inside torsos, no overlapping bodies")


def _line_span(b: dict) -> tuple[float, float]:
    words = b.get("words") or []
    if words:
        return float(words[0]["start"]), float(words[-1]["end"])
    return float(b["start"]), float(b["end"])


def _deliberate_cutaway(shot: dict) -> bool:
    return shot.get("type") == "insert" or "reaction" in (shot.get("reason") or "") or bool(shot.get("reaction"))


def gate_speaker_on_screen(an: dict, tl: dict, shots: list[dict]) -> Gate:
    fps = an["fps"]
    shot_meta = {s["id"]: s for s in shots}
    issues = []
    for b in tl.get("beats", []):
        spk = b.get("speaker")
        if not spk or not (b.get("line") or "").strip():
            continue
        t0, t1 = _line_span(b)
        if t1 - t0 < 1.2:
            continue
        seen, total, per_shot = 0, 0, {}
        for shot, smp in _all_samples(an):
            t = _time(smp["frame"], fps)
            if not t0 <= t <= t1 or _deliberate_cutaway(shot_meta.get(shot["id"], {})):
                continue
            total += 1
            vis = _visible((smp["chars"].get(spk) or {}).get("head_screen"))
            seen += vis
            if not vis:
                per_shot[shot["id"]] = per_shot.get(shot["id"], 0) + 1
        if total and seen / total < 0.5:
            worst = max(per_shot, key=per_shot.get) if per_shot else None
            issues.append({"beat": b["id"], "speaker": spk, "visible": round(seen / total, 2), "shot": worst,
                           "severity": "fail" if seen / total < 0.25 else "warn"})
    if issues:
        status = "fail" if any(i["severity"] == "fail" for i in issues) else "warn"
        overrides = {i["shot"]: {"subject": i["speaker"]} for i in issues if i["shot"] and i["severity"] == "fail"}
        return Gate("speaker_on_screen", status, f"{len(issues)} line(s) with the speaker mostly off screen", issues,
                    {"action": "shot_override", "overrides": overrides} if overrides else None)
    return Gate("speaker_on_screen", "pass", "every speaker is on screen for most of their line")


def _yaw_err(fwd, frm, to) -> float | None:
    if not fwd or not frm or not to:
        return None
    vx, vy = to[0] - frm[0], to[1] - frm[1]
    if math.hypot(vx, vy) < 1e-4 or math.hypot(fwd[0], fwd[1]) < 1e-4:
        return None
    a = math.atan2(fwd[1], fwd[0]) - math.atan2(vy, vx)
    return abs(math.degrees((a + math.pi) % (2 * math.pi) - math.pi))


def gate_eyelines(an: dict, tl: dict) -> Gate:
    fps = an["fps"]
    cast = set(tl.get("cast", []))
    issues = []
    for b in tl.get("beats", []):
        spk, add = b.get("speaker"), b.get("addressee")
        if not spk or not (b.get("line") or "").strip():
            continue
        t0, t1 = _line_span(b)
        if t1 - t0 < 1.0:
            continue
        sp_ok = sp_n = 0
        listen: dict[str, list[int]] = {}
        for _shot, smp in _all_samples(an):
            t = _time(smp["frame"], fps)
            if not t0 <= t <= t1:
                continue
            ch = smp["chars"]
            s = ch.get(spk) or {}
            if add in cast and add != spk:
                err = _yaw_err(s.get("head_fwd"), s.get("head"), (ch.get(add) or {}).get("head"))
                if err is not None:
                    sp_n += 1
                    sp_ok += err <= EYELINE_SPEAKER_DEG
            for lid in cast - {spk}:
                d = ch.get(lid) or {}
                if not _visible(d.get("head_screen"), 0.3):
                    continue
                err = _yaw_err(d.get("head_fwd"), d.get("head"), s.get("head"))
                if err is not None:
                    acc = listen.setdefault(lid, [0, 0])
                    acc[0] += err <= EYELINE_LISTENER_DEG
                    acc[1] += 1
        if sp_n >= 3 and sp_ok / sp_n < 0.5:
            issues.append({"beat": b["id"], "character": spk, "looks_at": add, "ok": round(sp_ok / sp_n, 2),
                           "role": "speaker"})
        for lid, (ok, n) in listen.items():
            if n >= 3 and ok / n < 0.4:
                issues.append({"beat": b["id"], "character": lid, "looks_at": spk, "ok": round(ok / n, 2),
                               "role": "listener"})
    if issues:
        speakers = [i for i in issues if i["role"] == "speaker"]
        status = "fail" if speakers else "warn"
        return Gate("eyelines", status, f"{len(speakers)} speaker / {len(issues) - len(speakers)} listener eyeline "
                    "miss(es)", issues, {"action": "look_boost", "characters": sorted({i["character"] for i in issues})})
    return Gate("eyelines", "pass", "speakers face their addressee and on-screen listeners watch the speaker")


def gate_static_shots(an: dict) -> Gate:
    fps = an["fps"]
    issues = []
    for shot in an.get("shots", []):
        samples = shot.get("samples", [])
        flags = []
        for prev, cur in zip(samples, samples[1:], strict=False):
            moving = False
            ca, cb = prev.get("camera"), cur.get("camera")
            if ca and cb:
                moving |= math.dist(ca["loc"], cb["loc"]) > 0.0015
                moving |= max(abs(x - y) for x, y in zip(ca["rot"], cb["rot"], strict=False)) > 0.0015
                moving |= abs(ca["lens"] - cb["lens"]) > 0.05
            for cid, d in cur["chars"].items():
                p = prev["chars"].get(cid) or {}
                if not _visible(d.get("head_screen"), 0.2):
                    continue
                for k in ("head", "hand.L", "hand.R", "chest"):
                    if d.get(k) and p.get(k) and math.dist(d[k], p[k]) > 0.0025:
                        moving = True
            flags.append((cur["frame"], not moving, shot["id"]))
        for a, b, _sid in _runs(flags, int(STATIC_MAX_S * fps)):
            issues.append({"shot": shot["id"], "frames": [a, b], "seconds": round((b - a) / fps, 2)})
    if issues:
        overrides = {i["shot"]: {"movement": "push_in", "movement_amount": 0.6} for i in issues}
        return Gate("static_shots", "fail", f"{len(issues)} frozen span(s) longer than {STATIC_MAX_S:.1f}s", issues,
                    {"action": "shot_override", "overrides": overrides})
    return Gate("static_shots", "pass", f"nothing is frozen for more than {STATIC_MAX_S:.1f}s")


def _spec_openness(tracks: dict, n: int) -> np.ndarray:
    """Per-frame mouth openness from the viseme shape-key keys Blender will play (scene spec)."""
    from storyforge.performance.lipsync import OPENNESS

    curve = np.zeros(n, dtype=np.float32)
    frames = np.arange(1, n + 1, dtype=np.float32)
    for name, keys in tracks.items():
        if not name.startswith("mouth_") or not keys:
            continue
        w = OPENNESS.get(name[len("mouth_"):], 0.0)
        if w <= 0:
            continue
        ks = np.asarray(keys, dtype=np.float32)
        curve += w * np.interp(frames, ks[:, 0], ks[:, 1], left=0.0, right=0.0)
    return curve


def _best_lag(mouth: np.ndarray, env: np.ndarray, max_lag: int = 5) -> float | None:
    n = min(len(mouth), len(env))
    mouth, env = mouth[:n], env[:n]
    if n < 10 or env.max() <= 0 or mouth.max() <= 0:
        return None
    env = (env - env.mean()) / (env.std() + 1e-9)
    m = (mouth - mouth.mean()) / (mouth.std() + 1e-9)
    best, best_lag = -1e18, 0
    for lag in range(-max_lag, max_lag + 1):
        v = float(np.dot(m[lag:], env[:n - lag])) if lag >= 0 else float(np.dot(m[:n + lag], env[-lag:]))
        if v > best:
            best, best_lag = v, lag
    return float(best_lag)


def gate_lipsync(ctx, tl: dict) -> Gate:
    """Cross-correlates each speaker's mouth openness (the keys in the scene spec, i.e. what Blender
    plays) with the envelope of the dialogue they speak in the final mix timing."""
    from storyforge.audio import dsp

    stem = ctx.path("audio", "stems", "dialogue.wav")
    spec = read_json(ctx.path("scene", "scene_spec.json"), None)
    if not stem.is_file() or not spec:
        return Gate("lipsync_offset", "skip", "no dialogue stem / scene spec yet")
    audio = dsp.load(stem, mono=True)
    lead = float(read_json(ctx.path("audio", "mix_stats.json"), {}).get("lead_seconds", 0.0) or 0.0)
    audio = audio[int(lead * dsp.SR):]
    fps = tl["fps"]
    n = tl["frames"]
    hop = dsp.SR // fps
    details, shifts = [], {}
    for ch in spec.get("characters", []):
        cid = ch["id"]
        mouth = _spec_openness((ch.get("face") or {}).get("mouth") or {}, n)
        if mouth.max() <= 0:
            continue
        # only this character's lines: mask the audio outside their speaking spans
        mask = np.zeros(len(audio), dtype=np.float32)
        for b in tl["beats"]:
            if b.get("speaker") == cid and b.get("audio"):
                a0, a1 = int(b["audio"]["start"] * dsp.SR), int(b["audio"]["end"] * dsp.SR)
                mask[max(0, a0):max(0, a1)] = 1.0
        sig = audio * mask
        env = np.array([np.sqrt(np.mean(sig[i * hop:(i + 1) * hop] ** 2)) if (i + 1) * hop <= len(sig) else 0.0
                        for i in range(n)], dtype=np.float32)
        lag = _best_lag(mouth, env)
        if lag is None:
            continue
        details.append({"character": cid, "offset_frames": lag})
        if abs(lag) > 1:
            shifts[cid] = -lag
    if shifts:
        return Gate("lipsync_offset", "fail", "mouth vs audio offset > 1 frame for " + ", ".join(
            f"{c} ({-s:+.0f}f)" for c, s in shifts.items()), details, {"action": "lipsync_shift", "shift": shifts})
    if not details:
        return Gate("lipsync_offset", "skip", "no lip-synced dialogue")
    worst = max(abs(d["offset_frames"]) for d in details)
    return Gate("lipsync_offset", "pass", f"mouths within {worst:.0f} frame(s) of the dialogue", details)


def run(ctx, tl: dict) -> list[Gate]:
    an = read_json(ctx.path("scene", "analysis.json"), None)
    gates: list[Gate] = []
    if not an:
        gates.append(Gate("animation", "skip", "no scene analysis (Blender build has not run)"))
    else:
        perf = read_json(ctx.path("performance.json"), {})
        shots = read_json(ctx.path("shotlist.json"), {"shots": []})["shots"]
        gates += [gate_rig(an), gate_tpose(an, perf), gate_foot_sliding(an, perf), gate_interpenetration(an),
                  gate_speaker_on_screen(an, tl, shots), gate_eyelines(an, tl), gate_static_shots(an)]
    gates.append(gate_lipsync(ctx, tl))
    return gates
