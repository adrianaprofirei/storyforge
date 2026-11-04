"""StoryForge Blender entry point.

Runs inside Blender:   blender -b --factory-startup --python-exit-code 1 -P entry.py -- <command> [args]
or with the bpy module: python entry.py -- <command> [args]

Commands:
  build    --spec scene_spec.json --blend out.blend [--analysis analysis.json]
  render   --blend in.blend --shot ID --start F --end F --out DIR [--preset draft] [--device AUTO]
  stills   --blend in.blend --frames F1,F2,... --out DIR [--preset draft]
  preview  --cast character.json --out preview.png [--style stylized_3d] [--turntable N]
  import-clip --file mocap.(bvh|fbx|glb) --out clip.json [--map map.json]
  import-character --file char.(blend|fbx|glb) --out info.json
  pack     --blend file.blend
  doctor
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402


def _args(argv: list[str]):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser(prog="storyforge_blender")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--spec", required=True)
    b.add_argument("--blend", required=True)
    b.add_argument("--analysis")
    r = sub.add_parser("render")
    r.add_argument("--blend", required=True)
    r.add_argument("--shot", required=True)
    r.add_argument("--start", type=int, required=True)
    r.add_argument("--end", type=int, required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--preset", default="draft")
    r.add_argument("--device", default="AUTO")
    r.add_argument("--style", default=None)
    r.add_argument("--max-frames", type=int, default=0)
    s = sub.add_parser("stills")
    s.add_argument("--blend", required=True)
    s.add_argument("--frames", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--preset", default="draft")
    s.add_argument("--device", default="AUTO")
    s.add_argument("--style", default=None)
    pv = sub.add_parser("preview")
    pv.add_argument("--cast", required=True)
    pv.add_argument("--out", required=True)
    pv.add_argument("--style", default="stylized_3d")
    pv.add_argument("--turntable", type=int, default=0)
    ic = sub.add_parser("import-clip")
    ic.add_argument("--file", required=True)
    ic.add_argument("--out", required=True)
    ic.add_argument("--map")
    pk = sub.add_parser("pack")
    pk.add_argument("--blend", required=True)
    ich = sub.add_parser("import-character")
    ich.add_argument("--file", required=True)
    ich.add_argument("--out", required=True)
    sub.add_parser("doctor")
    return p.parse_args(argv)


def cmd_build(a):
    from storyforge_blender.builder import build_scene, load_spec, log, save_blend

    spec = load_spec(a.spec)
    episode_dir = Path(spec.get("paths", {}).get("episode_dir") or Path(a.spec).parent.parent)
    built = build_scene(spec, episode_dir)
    save_blend(Path(a.blend))
    log(f"saved {a.blend}")
    if a.analysis:
        from storyforge_blender.analysis import analyze

        t = time.time()
        report = analyze(bpy.context.scene, spec, built)
        Path(a.analysis).write_text(json.dumps(report, indent=1), encoding="utf-8")
        log(f"analysis written in {time.time() - t:.1f}s")


def _open(blend: str):
    bpy.ops.wm.open_mainfile(filepath=blend)
    return bpy.context.scene


def _frame_handler(scene, *_):
    print(f"SF_FRAME_DONE {scene.frame_current}", flush=True)


def cmd_render(a):
    from storyforge_blender.render_settings import configure

    scene = _open(a.blend)
    style = a.style or scene.get("sf_style", "stylized_3d")
    info = configure(scene, a.preset, style, a.device, scene.render.fps,
                     volumetric_night=bool(scene.get("sf_night_volumetrics", False)))
    print(f"SF_LOG render device: {info}", flush=True)
    cam = bpy.data.objects.get(f"CAM_{a.shot}")
    if cam is not None:
        scene.camera = cam
        for m in scene.timeline_markers:  # only this shot's camera binding matters for the range
            if m.camera is not None and m.name != a.shot and a.start <= m.frame <= a.end:
                m.camera = cam
    end = a.end
    if a.max_frames:
        end = min(end, a.start + a.max_frames - 1)
    scene.frame_start, scene.frame_end = a.start, end
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(out / "frame_")
    bpy.app.handlers.render_post.append(_frame_handler)
    t = time.time()
    bpy.ops.render.render(animation=True)
    print(f"SF_LOG rendered {a.shot} frames {a.start}-{end} in {time.time() - t:.1f}s", flush=True)


def cmd_stills(a):
    from storyforge_blender.render_settings import configure

    scene = _open(a.blend)
    style = a.style or scene.get("sf_style", "stylized_3d")
    configure(scene, a.preset, style, a.device, scene.render.fps)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in [int(x) for x in a.frames.split(",") if x.strip()]:
        scene.frame_set(f)
        cam_marker = None
        for m in sorted(scene.timeline_markers, key=lambda m: m.frame):
            if m.frame <= f and m.camera is not None:
                cam_marker = m
        if cam_marker:
            scene.camera = cam_marker.camera
        scene.render.filepath = str(out / f"still_{f:05d}.png")
        bpy.ops.render.render(write_still=True)
        print(f"SF_FRAME_DONE {f}", flush=True)


def cmd_preview(a):
    from storyforge_blender.preview import render_preview

    render_preview(json.loads(Path(a.cast).read_text(encoding="utf-8")), a.out, a.style, a.turntable)


def cmd_import_clip(a):
    from storyforge_blender.retarget import import_clip

    mapping = json.loads(Path(a.map).read_text(encoding="utf-8")) if a.map else None
    clip = import_clip(a.file, mapping)
    Path(a.out).write_text(json.dumps(clip), encoding="utf-8")
    print(f"SF_LOG clip {clip['name']}: {clip['frames']} frames, {len(clip['bones'])} bones", flush=True)


def cmd_import_character(a):
    from storyforge_blender.importers import inspect_character

    info = inspect_character(a.file)
    Path(a.out).write_text(json.dumps(info, indent=1), encoding="utf-8")


def cmd_pack(a):
    """Pack external files (audio, textures) into the .blend and keep paths relative."""
    _open(a.blend)
    try:
        bpy.context.preferences.filepaths.save_version = 0
    except Exception:
        pass
    try:
        bpy.ops.file.pack_all()
    except Exception as exc:
        print(f"SF_LOG pack_all failed: {exc}", flush=True)
    bpy.ops.wm.save_mainfile(filepath=a.blend, compress=True)
    print(f"SF_LOG packed {a.blend}", flush=True)


def cmd_doctor(a):
    from storyforge_blender.render_settings import detect_gpu

    gpu = detect_gpu("AUTO")
    print("SF_DOCTOR " + json.dumps({"blender": bpy.app.version_string, "gpu": gpu,
                                     "python": sys.version.split()[0],
                                     "background": bpy.app.background}), flush=True)


def main():
    a = _args(sys.argv)
    try:
        {"build": cmd_build, "render": cmd_render, "stills": cmd_stills, "preview": cmd_preview,
         "import-clip": cmd_import_clip, "import-character": cmd_import_character, "pack": cmd_pack,
         "doctor": cmd_doctor}[a.cmd](a)
    except Exception:
        traceback.print_exc()
        print("SF_ERROR", flush=True)
        sys.stdout.flush()
        if bpy.app.background:
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
