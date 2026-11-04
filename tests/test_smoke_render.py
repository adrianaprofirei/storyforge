"""End-to-end smoke render: 5 seconds of the demo at low resolution, through every stage.

Needs Blender (BLENDER_PATH, or BLENDER_PYTHON with the bpy module) and ffmpeg; skipped with an
explanation otherwise. Takes a few minutes on a CPU, seconds with a GPU."""

from __future__ import annotations

import json
import subprocess

import pytest

pytestmark = [pytest.mark.blender, pytest.mark.slow]


def test_five_second_smoke_render(demo_project, require_blender, require_ffmpeg, settings):
    from storyforge.pipeline.context import EpisodeContext, RunOptions
    from storyforge.pipeline.runner import run_episode

    eid = "clock_that_stopped_p1"
    opts = RunOptions(preset="proxy", duration_limit=5.0, fps=12)
    logs = []
    ctx = EpisodeContext(demo_project, eid, opts, on_log=logs.append)
    reports = run_episode(ctx)
    statuses = {r.stage: r.status for r in reports}
    assert all(s in ("ran", "cached", "skipped") for s in statuses.values()), statuses
    for stage in ("voices", "timeline", "shots", "performance", "audio_mix", "build", "preflight", "render", "mux",
                  "quality", "deliverables"):
        assert statuses.get(stage) in ("ran", "cached"), (stage, statuses)

    video = ctx.path("output", f"{eid}_proxy.mp4")
    clean = ctx.path("output", f"{eid}_proxy_clean.mp4")
    assert video.is_file() and clean.is_file()
    probe = json.loads(subprocess.run(
        [settings.tool("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,sample_rate:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True).stdout)
    streams = {s["codec_type"]: s for s in probe["streams"]}
    assert streams["video"]["codec_name"] == "h264"
    assert (streams["video"]["width"], streams["video"]["height"]) == (270, 480)
    assert streams["audio"]["codec_name"] == "aac" and streams["audio"]["sample_rate"] == "48000"
    assert 4.5 <= float(probe["format"]["duration"]) <= 6.0

    report = json.loads(ctx.path("quality", "report_proxy.json").read_text())
    gates = {g["name"]: g["status"] for g in report["gates"]}
    assert gates["audio_clipping"] == "pass"
    assert gates["captions_safe_area"] == "pass"
    assert gates["unrigged"] == "pass" and gates["t_pose"] == "pass"
    assert ctx.path("output", f"{eid}.blend").is_file(), "an editable .blend is exported"
    assert list(ctx.path("output", "thumbnails").glob("proxy_*.png")), "thumbnail candidates are written"
