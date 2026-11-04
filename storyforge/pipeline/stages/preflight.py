"""preflight stage: quality gates before rendering, with automatic fixes.

Runs every gate that does not need rendered pixels (animation analysis, audio, captions, continuity,
runtime). Failing gates with a known fix are fixed in the stage that owns the problem
(storyforge/quality/autofix.py); those stages re-run (cache-aware) together with the scene build
and analysis, and the gates run again - up to MAX_ROUNDS. A *final* render does not start while
gates still fail unless the run asks to ignore them (CLI --ignore-gates / UI checkbox); drafts
continue with warnings so iteration stays fast.
"""

from __future__ import annotations

from storyforge.pipeline.runner import Stage
from storyforge.schemas import ValidationFailed
from storyforge.util.hashing import maybe_file_hash
from storyforge.util.io import read_json, write_json

MAX_ROUNDS = 3
RERUN = ["timeline", "shots", "performance", "audio_mix", "captions", "scene", "build"]
FINAL_PRESETS = ("final", "final_4k")


class PreflightStage(Stage):
    code = ("quality/*.py",)
    name = "preflight"
    version = "1"
    weight = 0.8

    def enabled(self, ctx):
        return not ctx.options.skip_render

    def inputs(self, ctx):
        return {"analysis": maybe_file_hash(ctx.path("scene", "analysis.json")),
                "mix": maybe_file_hash(ctx.path("audio", "mix.wav")),
                "layout": maybe_file_hash(ctx.path("captions", "layout.json")),
                "timeline": maybe_file_hash(ctx.path("timeline.json")),
                "shots": maybe_file_hash(ctx.path("shotlist.json")),
                "performance": maybe_file_hash(ctx.path("performance.json")),
                "continuity": maybe_file_hash(ctx.path("continuity.json")),
                "preset": ctx.options.preset, "autofix": ctx.options.autofix, "ignore": ctx.options.ignore_gates,
                "limited": bool(ctx.options.duration_limit)}

    def outputs(self, ctx):
        return [ctx.path("quality", f"preflight_{ctx.options.preset}.json")]

    def run(self, ctx):
        from storyforge.pipeline.runner import run_subset
        from storyforge.quality.autofix import FIXABLE, apply_fixes
        from storyforge.quality.gates import run_gates

        rounds = []
        report = run_gates(ctx, post_render=False)
        for i in range(MAX_ROUNDS):
            failing = [g for g in report["gates"] if g["status"] == "fail"]
            fixable = [g for g in failing if (g.get("fix") or {}).get("action") in FIXABLE]
            if not fixable or not ctx.options.autofix:
                break
            applied = apply_fixes(ctx, fixable)
            if not applied:
                break
            for a in applied:
                ctx.log(f"auto-fix ({a['gate']}): {a['detail']}")
            ctx.progress((i + 1) / (MAX_ROUNDS + 1), f"auto-fix round {i + 1}: re-running affected stages")
            reran = [r.stage for r in run_subset(ctx, RERUN) if r.status == "ran"]
            rounds.append({"round": i + 1, "fixed": [g["name"] for g in fixable], "applied": applied,
                           "reran": reran})
            report = run_gates(ctx, post_render=False)
        cont_gate = (ctx.bible().get("format", {}) or {}).get("continuity_gate", "warn")
        blocking = [g for g in report["gates"] if g["status"] == "fail"
                    and not (g["name"] == "continuity" and cont_gate != "block")]
        report.update({"rounds": rounds, "blocking": [g["name"] for g in blocking],
                       "autofix": ctx.options.autofix})
        write_json(ctx.path("quality", f"preflight_{ctx.options.preset}.json"), report)
        for g in report["gates"]:
            if g["status"] in ("fail", "warn"):
                ctx.log(f"gate {g['name']}: {g['status'].upper()} - {g['summary']}")
        if blocking and ctx.options.preset in FINAL_PRESETS and not ctx.options.ignore_gates:
            raise ValidationFailed([f"quality gate '{g['name']}' failed: {g['summary']}" for g in blocking] + [
                "the final render was not started; fix the issues (see the quality report) or re-run with "
                "--ignore-gates / the 'render anyway' option"])
        return {"passed": not blocking, "rounds": len(rounds),
                "fixed": sorted({n for r in rounds for n in r["fixed"]}), "blocking": [g["name"] for g in blocking]}


def preflight_summary(ctx) -> dict | None:
    rep = read_json(ctx.path("quality", f"preflight_{ctx.options.preset}.json"), None)
    if not rep:
        return None
    return {"passed": not rep.get("blocking"), "rounds": rep.get("rounds", []), "blocking": rep.get("blocking", [])}
