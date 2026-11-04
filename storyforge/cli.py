"""StoryForge command line.

    storyforge demo [--preset draft] [--parts 1,2]      bundled sample arc -> MP4s (no API keys needed)
    storyforge run --series ID --episode ID [...]      run/resume one part's pipeline (cached)
    storyforge plan-arc --series ID --idea "..."       plan a 2-5 part arc with the LLM
    storyforge arc --series ID --arc ID [...]          run all parts of an arc in order
    storyforge serve                                   web UI + API + render queue
    storyforge doctor                                  check tools, GPU and providers
    storyforge assets                                  (re)generate the built-in SFX/music/clip library
    storyforge schemas                                 export JSON Schemas to storyforge/schemas/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from storyforge.config import get_settings


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")


def _progress_printer():
    last = {"t": 0.0}

    def cb(frac: float, msg: str):
        now = time.time()
        if now - last["t"] > 2.0 or frac >= 1.0:
            last["t"] = now
            print(f"  [{frac * 100:5.1f}%] {msg}", flush=True)

    return cb


def run_part(project, episode_id: str, args) -> list:
    from storyforge.pipeline.context import EpisodeContext, RunOptions
    from storyforge.pipeline.runner import run_episode, summarize

    opts = RunOptions(preset=args.preset, force=set(filter(None, (args.force or "").split(","))),
                      only_shots=[s for s in (args.shots or "").split(",") if s] or None,
                      until=args.until, max_frames=args.max_frames or None, fps=args.fps or None,
                      duration_limit=args.duration or None, skip_render=args.no_render)
    ctx = EpisodeContext(project, episode_id, opts, on_progress=_progress_printer(),
                         on_log=lambda line: print(line, flush=True))
    t = time.time()
    reports = run_episode(ctx)
    print(f"\n{episode_id} finished in {time.time() - t:.1f}s\n{summarize(reports)}", flush=True)
    return reports


def cmd_demo(args) -> int:
    from storyforge.project import Project

    project = Project.ensure_demo(reset=args.reset)
    if args.style:
        def fn(b):
            b.setdefault("look", {})["style"] = args.style
            b["world"]["visual_style"] = args.style
        project.update_bible(fn, f"style -> {args.style}")
    eps = [e for e in project.episodes() if e.get("arc_id") == "clock_that_stopped"]
    parts = {int(p) for p in args.parts.split(",")} if args.parts else {e["part"] for e in eps}
    for e in sorted(eps, key=lambda e: e["part"]):
        if e["part"] in parts:
            print(f"\n=== {e['id']} (part {e['part']}) ===", flush=True)
            run_part(project, e["id"], args)
    out = project.root / "episodes"
    print(f"\nOutputs: {out}/<episode>/output/", flush=True)
    return 0


def cmd_run(args) -> int:
    from storyforge.project import Project

    project = Project.open(args.series)
    run_part(project, args.episode, args)
    return 0


def cmd_doctor(args) -> int:
    from storyforge.providers.tts import available_providers
    from storyforge.render.blender import doctor
    from storyforge.util.ffmpeg import capabilities

    s = get_settings()
    info = s.summary()
    info["ffmpeg_capabilities"] = capabilities()
    info["tts_available"] = available_providers(s)
    if not args.quick:
        info["blender_doctor"] = doctor(s)
    print(json.dumps(info, indent=2))
    return 0


def cmd_schemas(args) -> int:
    from storyforge.schemas import export_schemas

    for p in export_schemas():
        print(p)
    return 0


def cmd_assets(args) -> int:
    from storyforge.audio.library import ensure_library

    lib = ensure_library(force=args.force)
    print(json.dumps({k: len(v) for k, v in lib.items()}, indent=2))
    return 0


def cmd_plan_arc(args) -> int:
    from storyforge.project import Project
    from storyforge.story.arc import plan_arc

    project = Project.open(args.series)
    arc = plan_arc(project, args.idea, args.parts)
    print(json.dumps(arc, indent=2, ensure_ascii=False))
    return 0


def cmd_arc(args) -> int:
    """Run every part of an arc in order (parts 2+ build on the continuity log of earlier parts)."""
    from storyforge.project import Project

    project = Project.open(args.series)
    arc = project.arc(args.arc)
    if arc is None:
        print(f"unknown arc '{args.arc}'; known: {[a['arc_id'] for a in project.arcs()]}", file=sys.stderr)
        return 2
    parts = {int(p) for p in args.parts.split(",")} if args.parts else {p["part"] for p in arc["parts"]}
    for p in arc["parts"]:
        if p["part"] in parts:
            eid = project.episode_id_for(arc["arc_id"], p["part"])
            print(f"\n=== {eid} (part {p['part']}/{len(arc['parts'])}) ===", flush=True)
            run_part(project, eid, args)
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    s = get_settings()
    uvicorn.run("storyforge.api.app:app", host=args.host or s.host, port=args.port or s.port, reload=False,
                log_level="info")
    return 0


def _add_run_opts(p):
    p.add_argument("--preset", default=None, help="draft | final | final_4k | proxy")
    p.add_argument("--force", help="comma-separated stage names to re-run")
    p.add_argument("--shots", help="comma-separated shot ids to (re-)render")
    p.add_argument("--until", help="stop after this stage")
    p.add_argument("--max-frames", type=int, default=0, help="debug: render at most N frames per shot")
    p.add_argument("--fps", type=int, default=0, help="override fps (e.g. 12 for quick previews)")
    p.add_argument("--duration", type=float, default=0.0, help="cut the timeline after N seconds (smoke tests)")
    p.add_argument("--no-render", action="store_true", help="stop before Blender (story/audio only)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="storyforge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="render the bundled 2-part sample arc")
    _add_run_opts(d)
    d.add_argument("--parts", help="e.g. 1 or 1,2")
    d.add_argument("--style", choices=["stylized_3d", "cartoon"])
    d.add_argument("--reset", action="store_true", help="recreate the demo project from the samples")
    r = sub.add_parser("run", help="run one part's pipeline")
    _add_run_opts(r)
    r.add_argument("--series", required=True)
    r.add_argument("--episode", required=True)
    doc = sub.add_parser("doctor")
    doc.add_argument("--quick", action="store_true", help="skip launching Blender")
    sub.add_parser("schemas")
    a = sub.add_parser("assets")
    a.add_argument("--force", action="store_true")
    pa = sub.add_parser("plan-arc")
    pa.add_argument("--series", required=True)
    pa.add_argument("--idea", required=True)
    pa.add_argument("--parts", type=int, default=2)
    ar = sub.add_parser("arc", help="run all parts of an arc in order (e.g. --until continuity_log to only write)")
    _add_run_opts(ar)
    ar.add_argument("--series", required=True)
    ar.add_argument("--arc", required=True)
    ar.add_argument("--parts", help="e.g. 1 or 1,2")
    sv = sub.add_parser("serve")
    sv.add_argument("--host")
    sv.add_argument("--port", type=int)
    args = ap.parse_args(argv)
    _setup_logging(args.verbose)
    if hasattr(args, "preset") and args.preset is None:
        args.preset = get_settings().render_preset
    return {"demo": cmd_demo, "run": cmd_run, "doctor": cmd_doctor, "schemas": cmd_schemas, "assets": cmd_assets,
            "plan-arc": cmd_plan_arc, "arc": cmd_arc, "serve": cmd_serve}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
