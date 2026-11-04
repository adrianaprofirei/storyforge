"""Job kinds: what the render queue can run. Each kind declares its lane, locks and title."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from storyforge.config import Settings
from storyforge.util.hashing import stable_hash
from storyforge.util.io import read_json, write_json

STORY_STAGES = {"screenplay", "review", "continuity_log"}


@dataclass
class JobKind:
    run: Callable
    lane: Callable[[dict], str]
    locks: Callable[[dict], list[str]]
    title: Callable[[dict], str]
    normalize: Callable[[dict], dict] = lambda p: p


def _ep_lock(p: dict, eid: str | None = None) -> str:
    return f"{p['series']}:{eid or p['episode']}"


def _project(p: dict):
    from storyforge.project import Project

    return Project.open(p["series"])


def _run_options(p: dict, settings: Settings):
    from storyforge.pipeline.context import RunOptions

    return RunOptions(preset=p.get("preset") or settings.render_preset, force=set(p.get("force") or []),
                      only_shots=p.get("shots") or None, until=p.get("until") or None,
                      max_frames=p.get("max_frames") or None, fps=p.get("fps") or None,
                      duration_limit=p.get("duration") or None, skip_render=bool(p.get("no_render")),
                      autofix=bool(p.get("autofix", True)), ignore_gates=bool(p.get("ignore_gates", False)))


def episode_outputs(project, episode_id: str) -> list[dict]:
    out = project.episode_dir(episode_id) / "output"
    files = []
    if out.is_dir():
        for f in sorted(out.rglob("*")):
            if f.is_file():
                files.append({"name": f.relative_to(out).as_posix(), "size": f.stat().st_size,
                              "path": f.relative_to(project.root).as_posix()})
    return files


def _run_one(jc, project, episode_id: str, p: dict, settings: Settings) -> dict:
    from storyforge.pipeline.context import EpisodeContext
    from storyforge.pipeline.runner import run_episode

    ctx = EpisodeContext(project, episode_id, _run_options(p, settings), settings=settings, on_log=jc.log,
                         on_progress=jc.progress, cancel_event=jc.cancel_event)
    reports = run_episode(ctx)
    return {"episode": episode_id, "stages": [{k: v for k, v in asdict(r).items() if k != "key"} for r in reports],
            "outputs": episode_outputs(project, episode_id)}


# ------------------------------------------------------------------ handlers
def run_episode_job(jc, p, settings):
    project = _project(p)
    if p.get("regenerate"):  # write a fresh screenplay (new variation) before running
        d = project.episode_dir(p["episode"])
        (d / "screenplay.json").unlink(missing_ok=True)
        meta = project.episode_meta(p["episode"])
        project.save_episode_meta(p["episode"], {"variation": int(meta.get("variation", 0) or 0) + 1})
    if p.get("rerender_shots"):  # force a fresh render of these shots
        for sid in p["rerender_shots"]:
            shutil.rmtree(project.episode_dir(p["episode"]) / "render" / (p.get("preset") or settings.render_preset)
                          / sid, ignore_errors=True)
    return _run_one(jc, project, p["episode"], p, settings)


def run_arc_job(jc, p, settings):
    project = _project(p)
    arc = project.arc(p["arc"])
    if arc is None:
        raise KeyError(f"unknown arc {p['arc']}")
    parts = [x for x in arc["parts"] if not p.get("parts") or x["part"] in p["parts"]]
    results = []
    for i, part in enumerate(parts):
        eid = project.episode_id_for(arc["arc_id"], part["part"])
        jc.log(f"=== {eid} (part {part['part']}/{len(arc['parts'])}) ===")
        jc.sub_progress(i / len(parts), (i + 1) / len(parts))
        results.append(_run_one(jc, project, eid, p, settings))
    return {"arc": arc["arc_id"], "parts": results}


def plan_arc_job(jc, p, settings):
    from storyforge.providers.llm import get_llm
    from storyforge.story.arc import plan_arc

    project = _project(p)
    jc.progress(0.05, "planning the arc")
    llm = get_llm(settings)
    jc.log(f"LLM: {llm.describe()}")
    arc = plan_arc(project, p["idea"], int(p.get("parts", 2)), llm=llm, variation=int(p.get("variation", 0)))
    for call in llm.calls:
        jc.log(f"llm {call.task}: attempts={call.attempts} usage={call.usage} served_by={call.served_model or '-'}")
    return {"arc_id": arc["arc_id"], "title": arc["title"],
            "episodes": [project.episode_id_for(arc["arc_id"], x["part"]) for x in arc["parts"]]}


def storyboard_job(jc, p, settings):
    """One still per shot (mid-shot frame) at proxy quality -> storyboard/<shot>.png + index.json."""
    from storyforge.render.blender import run_blender

    project = _project(p)
    eid = p["episode"]
    jc.sub_progress(0.0, 0.4)
    _run_one(jc, project, eid, {**p, "until": "build", "preset": "proxy"}, settings)
    d = project.episode_dir(eid)
    spec = read_json(d / "scene" / "scene_spec.json")
    shots = spec["shots"]
    frames = {s["id"]: (s["frame_start"] + s["frame_end"]) // 2 for s in shots}
    out = d / "storyboard"
    tmp = Path(tempfile.mkdtemp(prefix="sf_board_", dir=str(d)))
    jc.sub_progress(0.4, 1.0)
    done = {"n": 0}

    def on_frame(_f):
        done["n"] += 1
        jc.progress(done["n"] / max(1, len(frames)), f"{done['n']}/{len(frames)} shots")

    try:
        run_blender(settings, "stills", ["--blend", str(d / "scene" / "episode.blend"),
                                         "--frames", ",".join(str(f) for f in frames.values()), "--out", str(tmp),
                                         "--preset", "proxy", "--device", settings.render_device,
                                         "--style", spec["style"]["preset"]],
                    on_frame=on_frame, cancel_event=jc.cancel_event, on_log=jc.log)
        out.mkdir(exist_ok=True)
        sl = {s["id"]: s for s in read_json(d / "shotlist.json", {"shots": []})["shots"]}
        tl = read_json(d / "timeline.json", {"beats": []})
        beats = {b["id"]: b for b in tl.get("beats", [])}
        index = []
        for sid, f in frames.items():
            src = tmp / f"still_{f:05d}.png"
            if not src.is_file():
                continue
            shutil.move(str(src), out / f"{sid}.png")
            s = sl.get(sid, {})
            b = beats.get(s.get("beat"), {})
            index.append({"shot": sid, "frame": f, "image": f"storyboard/{sid}.png", "type": s.get("type"),
                          "subject": s.get("subject"), "lens_mm": s.get("lens_mm"),
                          "movement": (s.get("movement") or {}).get("type"), "start": s.get("start"),
                          "end": s.get("end"), "beat": s.get("beat"), "speaker": b.get("speaker"),
                          "line": b.get("line"), "action": b.get("action")})
        write_json(out / "index.json", {"episode": eid, "shots": index})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"shots": len(index), "index": f"episodes/{eid}/storyboard/index.json"}


def preview_character_job(jc, p, settings):
    """Blender still of a (possibly unsaved) cast entry for the character editor."""
    from storyforge.render.blender import run_blender
    from storyforge.schemas import ValidationFailed, schema_errors

    project = _project(p)
    entry = p.get("cast") or project.cast_member(p["character"])
    errors = schema_errors("cast_member", entry)
    if errors:
        raise ValidationFailed(errors)
    style = p.get("style") or (project.bible().get("look", {}) or {}).get("style") or "stylized_3d"
    key = stable_hash([entry, style, p.get("turntable", 0)], 16)
    out_dir = project.root / "previews"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{entry['id']}_{key}.png"
    if not out.is_file():
        imp = entry.get("import") or {}
        if imp.get("file"):
            entry = {**entry, "import": {**imp, "file": str(project.character_file(imp["file"]))}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(entry, fh)
            cast_file = fh.name
        try:
            jc.progress(0.1, "rendering preview")
            run_blender(settings, "preview", ["--cast", cast_file, "--out", str(out), "--style", style,
                                              "--turntable", str(int(p.get("turntable", 0)))],
                        cancel_event=jc.cancel_event, on_log=jc.log, timeout=900)
        finally:
            Path(cast_file).unlink(missing_ok=True)
    return {"image": out.relative_to(project.root).as_posix(), "character": entry["id"]}


def inspect_character_job(jc, p, settings):
    """Inspect an imported rigged character (bones, auto bone map, shape keys) for the cast editor."""
    from storyforge.render.blender import run_blender

    project = _project(p)
    src = project.character_file(p["file"])
    if not src.is_file():
        raise FileNotFoundError(src)
    out = project.root / "previews" / f"inspect_{stable_hash(str(src), 10)}.json"
    out.parent.mkdir(exist_ok=True)
    run_blender(settings, "import-character", ["--file", str(src), "--out", str(out)],
                cancel_event=jc.cancel_event, on_log=jc.log, timeout=900)
    info = read_json(out)
    return {"file": p["file"], "report": info}


def _norm_episode(p: dict) -> dict:
    p = dict(p)
    if "series" not in p or "episode" not in p:
        raise ValueError("series and episode are required")
    return p


HANDLERS: dict[str, JobKind] = {
    "run_episode": JobKind(
        run=run_episode_job,
        lane=lambda p: "story" if (p.get("until") in STORY_STAGES or p.get("no_render")) else "render",
        locks=lambda p: [_ep_lock(p)],
        title=lambda p: (f"{'Write' if p.get('until') in STORY_STAGES else 'Render'} {p['episode']}"
                         + (f" ({p.get('preset')})" if p.get("until") not in STORY_STAGES and p.get("preset") else "")
                         + (f" until {p['until']}" if p.get("until") and p.get("until") not in STORY_STAGES else "")
                         + (f" shots {','.join(p['shots'])}" if p.get("shots") else "")),
        normalize=_norm_episode),
    "run_arc": JobKind(
        run=run_arc_job,
        lane=lambda p: "story" if (p.get("until") in STORY_STAGES or p.get("no_render")) else "render",
        locks=lambda p: [f"{p['series']}:arc:{p['arc']}"] + [f"{p['series']}:{p['arc']}_p{i}" for i in range(1, 6)],
        title=lambda p: f"{'Write' if p.get('until') in STORY_STAGES else 'Render'} arc {p['arc']}"
                        + (f" ({p.get('preset')})" if p.get("until") not in STORY_STAGES and p.get("preset") else "")),
    "plan_arc": JobKind(
        run=plan_arc_job, lane=lambda p: "story", locks=lambda p: [f"{p['series']}:planner"],
        title=lambda p: f"Plan {p.get('parts', 2)}-part arc: {p['idea'][:60]}"),
    "storyboard": JobKind(
        run=storyboard_job, lane=lambda p: "render", locks=lambda p: [_ep_lock(p)],
        title=lambda p: f"Storyboard {p['episode']}", normalize=_norm_episode),
    "preview_character": JobKind(
        run=preview_character_job, lane=lambda p: "preview",
        locks=lambda p: [f"{p['series']}:preview:{(p.get('cast') or {}).get('id') or p.get('character')}"],
        title=lambda p: f"Preview {(p.get('cast') or {}).get('id') or p.get('character')}"),
    "inspect_character": JobKind(
        run=inspect_character_job, lane=lambda p: "preview", locks=lambda p: [f"{p['series']}:inspect"],
        title=lambda p: f"Inspect {p['file']}"),
}
