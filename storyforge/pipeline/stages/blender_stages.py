"""scene (spec compile) + build (Blender .blend) + render (per shot, cached, resumable, parallel)."""

from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from storyforge.config import BLENDER_PKG_DIR
from storyforge.pipeline.runner import Stage
from storyforge.render.blender import run_blender
from storyforge.scene_spec import compile_spec, shot_fingerprint
from storyforge.util.hashing import maybe_file_hash, stable_hash, tree_hash
from storyforge.util.io import read_json, write_json

BLENDER_CODE_PATTERNS = ["*.py"]


def blender_code_hash() -> str:
    return tree_hash(BLENDER_PKG_DIR, BLENDER_CODE_PATTERNS)


def grade_for(ctx) -> dict:
    look = ctx.bible().get("look", {}) or {}
    return look.get("grade", {}) or {}


class SceneSpecStage(Stage):
    name = "scene"
    version = "1"
    weight = 0.3

    def inputs(self, ctx):
        return {"timeline": maybe_file_hash(ctx.path("timeline.json")),
                "shots": maybe_file_hash(ctx.path("shotlist.json")),
                "blocking": maybe_file_hash(ctx.path("blocking.json")),
                "performance": maybe_file_hash(ctx.path("performance.json")),
                "cast": stable_hash(ctx.cast()), "style": ctx.style(), "grade": grade_for(ctx),
                "preset": ctx.options.preset, "device": ctx.settings.render_device,
                "code": tree_hash(Path(__file__).resolve().parents[2], ["scene_spec.py", "cinematography/*.py",
                                                                         "lighting/*.py", "performance/*.py"])}

    def outputs(self, ctx):
        return [ctx.path("scene", "scene_spec.json")]

    def run(self, ctx):
        tl = read_json(ctx.path("timeline.json"))
        spec = compile_spec(
            episode_id=ctx.episode_id, timeline=tl, shotlist=read_json(ctx.path("shotlist.json")),
            blocking=read_json(ctx.path("blocking.json")), cast=ctx.cast(), bible=ctx.bible(), style=ctx.style(),
            grade=grade_for(ctx), preset=ctx.options.preset, device=ctx.settings.render_device,
            episode_dir=str(ctx.dir), performance=read_json(ctx.path("performance.json"), None))
        write_json(ctx.path("scene", "scene_spec.json"), spec, indent=None)
        return {"shots": len(spec["shots"]), "frames": spec["frame_end"]}


class BuildStage(Stage):
    name = "build"
    version = "1"
    weight = 2.0

    def enabled(self, ctx):
        return not ctx.options.skip_render

    def inputs(self, ctx):
        return {"spec": maybe_file_hash(ctx.path("scene", "scene_spec.json")),
                "mix": maybe_file_hash(ctx.path("audio", "mix.wav")), "code": blender_code_hash()}

    def outputs(self, ctx):
        return [ctx.path("scene", "episode.blend"), ctx.path("scene", "analysis.json")]

    def run(self, ctx):
        spec_path = ctx.path("scene", "scene_spec.json")
        blend = ctx.path("scene", "episode.blend")
        analysis = ctx.path("scene", "analysis.json")
        analysis.unlink(missing_ok=True)
        run_blender(ctx.settings, "build", ["--spec", str(spec_path), "--blend", str(blend), "--analysis", str(analysis)],
                    on_log=ctx.log, cancel_event=ctx.cancel_event, log_file=ctx.path("scene", "build.log"))
        if not analysis.is_file():
            write_json(analysis, {"note": "analysis unavailable"})
        return {"blend": str(blend)}


class RenderStage(Stage):
    """Renders every shot into render/<preset>/<shot_id>/frame_####.png.

    Per-shot cache key = shot fingerprint (global look + the shot + animation in its frame range)
    + blender code hash + preset, stored in <shot dir>/.key; a shot is re-rendered only when its
    key changes. Interrupted renders resume (Blender skips frames that already exist)."""

    name = "render"
    version = "1"
    weight = 30.0

    def enabled(self, ctx):
        return not ctx.options.skip_render

    def inputs(self, ctx):
        spec = read_json(ctx.path("scene", "scene_spec.json"))
        return {"shots": self._keys(ctx, spec), "preset": ctx.options.preset, "max_frames": ctx.options.max_frames}

    def outputs(self, ctx):
        return [ctx.path("render", ctx.options.preset, "manifest.json")]

    def _keys(self, ctx, spec) -> dict:
        code = blender_code_hash()
        return {s["id"]: stable_hash(shot_fingerprint(spec, s["id"]), code, ctx.options.preset, ctx.options.max_frames)
                for s in spec["shots"]}

    def run(self, ctx):
        spec = read_json(ctx.path("scene", "scene_spec.json"))
        preset = ctx.options.preset
        root = ctx.sub("render", preset)
        keys = self._keys(ctx, spec)
        blend = ctx.path("scene", "episode.blend")
        shots = spec["shots"]
        todo = []
        for s in shots:
            d = root / s["id"]
            key_file = d / ".key"
            expected = s["frame_end"] - s["frame_start"] + 1
            if ctx.options.max_frames:
                expected = min(expected, ctx.options.max_frames)
            done = len(list(d.glob("frame_*.png"))) if d.is_dir() else 0
            if key_file.is_file() and key_file.read_text().strip() == keys[s["id"]] and done >= expected:
                continue
            if key_file.is_file() and key_file.read_text().strip() != keys[s["id"]]:
                shutil.rmtree(d, ignore_errors=True)  # stale content: re-render from scratch
            if ctx.options.only_shots and s["id"] not in ctx.options.only_shots and done >= expected:
                continue
            todo.append(s)
        total_frames = sum(min(s["frame_end"] - s["frame_start"] + 1, ctx.options.max_frames or 10 ** 9) for s in todo)
        ctx.log(f"{len(todo)}/{len(shots)} shots to render ({total_frames} frames), preset={preset}")
        done_frames = 0
        lock = threading.Lock()
        t0 = time.time()

        def on_frame(_f):
            nonlocal done_frames
            with lock:
                done_frames += 1
                el = time.time() - t0
                eta = el / done_frames * (total_frames - done_frames) if done_frames else 0
                ctx.progress(done_frames / max(1, total_frames), f"{done_frames}/{total_frames} frames, ETA {eta:.0f}s")

        def render_one(s):
            d = root / s["id"]
            d.mkdir(parents=True, exist_ok=True)
            args = ["--blend", str(blend), "--shot", s["id"], "--start", str(s["frame_start"]), "--end", str(s["frame_end"]),
                    "--out", str(d), "--preset", preset, "--device", ctx.settings.render_device,
                    "--style", spec["style"]["preset"]]
            if ctx.options.max_frames:
                args += ["--max-frames", str(ctx.options.max_frames)]
            run_blender(ctx.settings, "render", args, on_log=ctx.log, on_frame=on_frame, cancel_event=ctx.cancel_event,
                        log_file=d / "render.log")
            (d / ".key").write_text(keys[s["id"]])
            return s["id"]

        workers = max(1, ctx.settings.render_workers)
        if workers == 1:
            for s in todo:
                ctx.check_cancel()
                render_one(s)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(render_one, s) for s in todo]
                for fut in as_completed(futs):
                    fut.result()
        manifest = {"preset": preset, "fps": spec["fps"], "frame_start": spec["frame_start"],
                    "frame_end": spec["frame_end"], "shots": []}
        for s in shots:
            d = root / s["id"]
            frames = sorted(d.glob("frame_*.png"))
            manifest["shots"].append({"id": s["id"], "frame_start": s["frame_start"], "frame_end": s["frame_end"],
                                      "dir": str(d.relative_to(ctx.dir)), "frames": len(frames), "key": keys[s["id"]]})
        write_json(root / "manifest.json", manifest)
        return {"rendered_shots": len(todo), "frames": done_frames, "seconds": round(time.time() - t0, 1)}
