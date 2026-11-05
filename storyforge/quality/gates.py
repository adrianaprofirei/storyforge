"""Automated quality gates run before/after a render. Each gate returns pass/warn/fail with a
summary, details and (where possible) an auto-fix that the pipeline can apply."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from storyforge.audio import dsp
from storyforge.captions.ass import SAFE
from storyforge.util.io import read_json


@dataclass
class Gate:
    name: str
    status: str  # pass | warn | fail | skip
    summary: str
    details: list = field(default_factory=list)
    fix: dict | None = None


def gate_audio_clipping(mix_path) -> Gate:
    if not mix_path.is_file():
        return Gate("audio_clipping", "skip", "no mix")
    audio = dsp.load(mix_path, mono=False)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    clipped = int(np.sum(np.abs(audio) >= 0.9999))
    if clipped:
        return Gate("audio_clipping", "fail", f"{clipped} clipped samples (peak {dsp.gain_to_db(peak):.2f} dBFS)",
                    fix={"action": "relimit_mix"})
    return Gate("audio_clipping", "pass", f"no clipping (sample peak {dsp.gain_to_db(peak):.2f} dBFS)")


def gate_loudness(mix_path, video_path=None, target=-14.0, tol=1.0, ceiling=-1.0) -> Gate:
    if not mix_path.is_file():
        return Gate("loudness", "skip", "no mix")
    audio = dsp.load(mix_path, mono=False)
    lufs = dsp.integrated_loudness(audio)
    tp = dsp.true_peak_db(audio)
    details = [{"source": "mix.wav", "integrated_lufs": round(lufs, 2), "true_peak_dbtp": round(tp, 2)}]
    if video_path is not None and video_path.is_file():
        from storyforge.util.ffmpeg import ebur128_stats

        st = ebur128_stats(video_path)
        if st:
            details.append({"source": video_path.name, **st})
            lufs = st.get("integrated_lufs", lufs)
            tp = max(tp, st.get("true_peak_dbtp", tp))
    ok_l = abs(lufs - target) <= tol
    ok_p = tp <= ceiling + 0.05
    status = "pass" if ok_l and ok_p else "fail"
    return Gate("loudness", status, f"{lufs:.1f} LUFS integrated (target {target:+.0f} +-{tol:.0f}), "
                f"true peak {tp:.2f} dBTP (<= {ceiling:.0f})", details,
                None if status == "pass" else {"action": "renormalize_mix"})


def gate_captions_safe_area(layout: dict) -> Gate:
    bad = []
    for ln in layout.get("lines", []):
        w = ln["play_w"] * (1 - SAFE["left"] - SAFE["right"])
        bottom_frac = ln["margin_v"] / ln["play_h"]
        if ln["width_px"] > w * 1.001 or bottom_frac < SAFE["bottom"]:
            bad.append({"t": round(ln["start"], 2), "text": ln["text"], "width_px": ln["width_px"], "max_px": round(w)})
    if bad:
        return Gate("captions_safe_area", "fail", f"{len(bad)} caption lines outside the safe area", bad,
                    {"action": "reflow_captions"})
    return Gate("captions_safe_area", "pass", f"{len(layout.get('lines', []))} caption lines inside the safe area")


def gate_runtime(timeline: dict, bible: dict, limited: bool) -> Gate:
    fmt = bible.get("format", {})
    lo, hi = float(fmt.get("part_min_seconds", 45)), float(fmt.get("part_max_seconds", 90))
    d = timeline["duration"]
    if limited:
        return Gate("runtime", "skip", f"duration limited for a test render ({d:.1f}s)")
    if lo <= d <= hi:
        return Gate("runtime", "pass", f"{d:.1f}s within {lo:.0f}-{hi:.0f}s")
    return Gate("runtime", "warn", f"{d:.1f}s outside {lo:.0f}-{hi:.0f}s")


def gate_continuity(report: dict | None) -> Gate:
    if not report:
        return Gate("continuity", "skip", "no continuity check")
    counts = report.get("counts", {})
    issues = report.get("issues", [])
    open_issues = [i for i in issues if i.get("status") == "open"]
    fixed = [i for i in issues if i.get("status") == "auto_fixed"]
    status = "fail" if counts.get("error") else ("warn" if counts.get("warning") else "pass")
    summary = (f"{counts.get('error', 0)} errors, {counts.get('warning', 0)} warnings, {counts.get('info', 0)} notes "
               f"against {len(report.get('checked_against', []))} earlier episodes")
    if fixed:
        summary += f"; {len(fixed)} auto-fixed ({', '.join(sorted({i['beat_id'] for i in fixed if i.get('beat_id')}))})"
    fix = None
    if status == "fail":
        fix = {"action": "edit_beats", "beats": sorted({i["beat_id"] for i in open_issues
                                                        if i.get("beat_id") and i["severity"] == "error"})}
    return Gate("continuity", status, summary, open_issues + fixed, fix)


def run_gates(ctx, post_render: bool = True) -> dict:
    """All gates. Before rendering (preflight) the loudness is measured on the mix; after muxing it is
    measured on the encoded MP4 too (AAC can add true-peak overshoot)."""
    p = ctx.options.preset
    tl = read_json(ctx.path("timeline.json"))
    gates: list[Gate] = []
    mix = ctx.path("audio", "mix.wav")
    video = ctx.path("output", f"{ctx.episode_id}_{p}.mp4")
    gates.append(gate_audio_clipping(mix))
    gates.append(gate_loudness(mix, video if post_render and video.is_file() else None))
    gates.append(gate_captions_safe_area(read_json(ctx.path("captions", "layout.json"), {"lines": []})))
    gates.append(gate_runtime(tl, ctx.bible(), bool(ctx.options.duration_limit)))
    gates.append(gate_continuity(read_json(ctx.path("continuity.json"), None)))
    try:
        from storyforge.quality import animation_gates

        gates.extend(animation_gates.run(ctx, tl))
    except ImportError:
        pass
    passed = all(g.status in ("pass", "warn", "skip") for g in gates)
    return {"episode": ctx.episode_id, "preset": p, "stage": "post_render" if post_render else "preflight",
            "passed": passed, "gates": [asdict(g) for g in gates]}
