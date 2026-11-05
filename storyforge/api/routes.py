"""REST API used by the web UI (all JSON; long work is submitted to the job queue)."""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from storyforge.config import ASSETS_DIR, get_settings
from storyforge.jobs.manager import get_manager
from storyforge.project import Project, bible_diff
from storyforge.schemas import ValidationFailed, get_schema, schema_errors
from storyforge.util.io import read_json, read_yaml, write_json, write_yaml

router = APIRouter(prefix="/api")

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
UPLOAD_KINDS = {"character": {".blend", ".fbx", ".glb", ".gltf"}, "animation": {".fbx", ".bvh", ".glb", ".gltf"},
                "sfx": {".wav", ".flac", ".ogg", ".mp3", ".aiff", ".aif"},
                "music": {".wav", ".flac", ".ogg", ".mp3", ".aiff", ".aif"}}
OPENAI_VOICES = ["alloy", "ash", "ballad", "cedar", "coral", "echo", "fable", "marin", "nova", "onyx", "sage",
                 "shimmer", "verse"]


# ------------------------------------------------------------------ helpers
def _project(sid: str) -> Project:
    if not ID_RE.match(sid or ""):
        raise HTTPException(404, f"unknown series '{sid}'")
    try:
        return Project.open(sid)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, f"unknown series '{sid}'") from exc


def _episode(project: Project, eid: str) -> Path:
    d = project.root / "episodes" / eid
    if not ID_RE.match(eid or "") or not d.is_dir():
        raise HTTPException(404, f"unknown episode '{eid}'")
    return d


def file_url(project: Project, path: Path | str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    try:
        rel = p.resolve().relative_to(project.root.resolve()).as_posix()
    except ValueError:
        return None
    v = int(p.stat().st_mtime) if p.exists() else 0
    return f"/api/files/{project.series_id}/{rel}?v={v}"


def _submit(kind: str, params: dict) -> dict:
    try:
        return get_manager().submit(kind, params)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _stage_records(d: Path) -> dict:
    out = {}
    for p in sorted((d / ".cache").glob("*.json")):
        rec = read_json(p, {})
        out[p.stem] = {"finished_at": rec.get("finished_at"), "seconds": rec.get("seconds"),
                       "info": rec.get("info")}
    return out


# ------------------------------------------------------------------ system
@router.get("/health")
def health():
    from storyforge import __version__

    return {"ok": True, "version": __version__}


@router.get("/system")
def system():
    from storyforge.providers.llm import get_llm
    from storyforge.providers.tts import available_providers
    from storyforge.util.ffmpeg import capabilities

    s = get_settings()
    info = s.summary()
    try:
        info["llm"] = get_llm(s).describe()
    except Exception as exc:  # e.g. missing key for a forced provider
        info["llm"] = {"provider": "error", "error": str(exc)}
    tts = available_providers(s)
    info["tts_providers"] = tts
    info["tts_available"] = [k for k, ok in tts.items() if ok and k != "silent"] if isinstance(tts, dict) else list(tts)
    try:
        info["ffmpeg_capabilities"] = capabilities()
    except Exception as exc:
        info["ffmpeg_capabilities"] = {"error": str(exc)}
    info["jobs_running"] = get_manager().running()
    return info


@router.get("/options")
def options():
    from storyforge.captions.ass import STYLE_PRESETS as CAPTION_STYLES
    from storyforge.lighting.grades import GRADE_PRESETS
    from storyforge.models import constants as C
    from storyforge.pipeline.stages import STAGE_NAMES
    from storyforge.schemas.definitions import CAMERA_HINTS
    from storyforge_blender.locations_data import LOCATIONS

    s = get_settings()
    piper = sorted(p.stem for p in Path(s.piper_voices_dir).glob("*.onnx")) if Path(s.piper_voices_dir).is_dir() else []
    return {
        "emotions": C.EMOTIONS, "gestures": C.GESTURES, "locomotion": C.LOCOMOTION, "props": C.PROPS,
        "prop_actions": C.PROP_ACTIONS, "emotion_fx": C.EMOTION_FX, "shot_types": C.SHOT_TYPES,
        "camera_moves": C.CAMERA_MOVES, "camera_hints": CAMERA_HINTS, "beat_types": C.BEAT_TYPES,
        "times_of_day": C.TIMES_OF_DAY, "music_moods": C.MUSIC_MOODS, "paces": C.PACES, "volumes": C.VOLUMES,
        "styles": C.STYLE_PRESETS, "surfaces": C.SURFACES, "rooms": C.ROOM_TYPES,
        "grades": {k: v for k, v in GRADE_PRESETS.items()}, "caption_styles": sorted(CAPTION_STYLES),
        "locations": {k: {"name": v.get("name", k), "kind": v.get("kind"), "description": v.get("description", "")}
                      for k, v in LOCATIONS.items()},
        "hair_styles": ["short", "spiky", "ponytail", "bun", "bob", "long", "curly", "bald"],
        "accessories": ["goggles", "glasses", "beanie", "cap", "backpack", "headphones", "bowtie"],
        "tops": ["tshirt", "hoodie", "cardigan", "jacket", "sweater"], "bottoms": ["pants", "shorts"],
        "patterns": ["solid", "stripes", "plaid", "dots", "gradient", "emblem"],
        "body_keys": ["height", "head_size", "torso_width", "torso_depth", "limb_thickness", "leg_length", "arm_length"],
        "color_keys": ["skin", "top", "top_accent", "bottom", "shoes", "hair", "eyes", "lips"],
        "voices": {"openai": OPENAI_VOICES, "piper": piper},
        "presets": ["proxy", "draft", "final", "final_4k"], "stages": STAGE_NAMES,
        "object_statuses": C.OBJECT_STATUSES,
    }


@router.get("/schemas/{name}")
def schema(name: str):
    try:
        return get_schema(name)
    except KeyError as exc:
        raise HTTPException(404, f"unknown schema {name}") from exc


# ------------------------------------------------------------------ series
@router.get("/series")
def list_series():
    out = []
    for p in Project.list():
        try:
            b = p.bible()
        except Exception:
            continue
        out.append({"id": p.series_id, "title": b.get("title"), "logline": b.get("logline"),
                    "version": b.get("version"), "arcs": len(p.arcs()), "episodes": len(p.episodes()),
                    "style": (b.get("look") or {}).get("style") or b.get("world", {}).get("visual_style")})
    return out


@router.post("/series")
def create_series(payload: dict = Body(...)):
    from storyforge.project import SAMPLES_DIR

    template = payload.get("template", "demo")
    if template == "demo":
        p = Project.ensure_demo()
        return {"id": p.series_id}
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    from storyforge.util.text import slugify

    sid = payload.get("series_id") or slugify(title, 40)
    if not ID_RE.match(sid):
        raise HTTPException(400, f"invalid series id '{sid}'")
    if (Project.projects_dir() / sid).exists():
        raise HTTPException(409, f"series '{sid}' already exists")
    bible = read_yaml(SAMPLES_DIR / "bible.yaml")
    bible.update({"series_id": sid, "title": title, "logline": payload.get("logline") or bible.get("logline", ""),
                  "arcs": [], "episodes": [], "continuity_log": []})
    cast = read_yaml(SAMPLES_DIR / "cast.yaml")
    try:
        p = Project.create(bible, cast)
    except ValidationFailed as exc:
        raise HTTPException(422, {"errors": exc.errors}) from exc
    return {"id": p.series_id}


@router.get("/series/{sid}")
def get_series(sid: str):
    p = _project(sid)
    b = p.bible()
    return {"id": sid, "title": b.get("title"), "logline": b.get("logline"), "version": b.get("version"),
            "arcs": p.arcs(), "episodes": p.episodes(), "cast": sorted(p.cast()),
            "bible_episodes": b.get("episodes", []), "bible_arcs": b.get("arcs", [])}


# ------------------------------------------------------------------ bible
@router.get("/series/{sid}/bible")
def get_bible(sid: str):
    p = _project(sid)
    b = p.bible()
    return {"bible": b, "yaml": p.bible_path.read_text(encoding="utf-8"), "version": b.get("version")}


@router.put("/series/{sid}/bible")
def put_bible(sid: str, payload: dict = Body(...)):
    p = _project(sid)
    if "yaml" in payload:
        try:
            doc = yaml.safe_load(payload["yaml"])
        except yaml.YAMLError as exc:
            raise HTTPException(422, {"errors": [f"YAML: {exc}"]}) from exc
    else:
        doc = payload.get("bible")
    if not isinstance(doc, dict):
        raise HTTPException(422, {"errors": ["the bible must be a mapping"]})
    if doc.get("series_id") != sid:
        raise HTTPException(422, {"errors": [f"series_id must stay '{sid}'"]})
    try:
        version = p.save_bible(doc, message=payload.get("message") or "edited in the bible editor")
    except ValidationFailed as exc:
        raise HTTPException(422, {"errors": exc.errors}) from exc
    return {"version": version}


@router.get("/series/{sid}/bible/versions")
def bible_versions(sid: str):
    return list(reversed(_project(sid).bible_versions()))


@router.get("/series/{sid}/bible/versions/{version}")
def bible_version(sid: str, version: int):
    p = _project(sid)
    try:
        return p.bible_version(version)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"no version {version}") from exc


@router.post("/series/{sid}/bible/versions/{version}/restore")
def bible_restore(sid: str, version: int):
    p = _project(sid)
    try:
        return {"version": p.restore_bible_version(version)}
    except ValidationFailed as exc:
        raise HTTPException(422, {"errors": exc.errors}) from exc


@router.get("/series/{sid}/bible/diff")
def bible_diff_route(sid: str, a: int, b: int):
    p = _project(sid)
    return bible_diff(p.bible_version(a), p.bible_version(b))


# ------------------------------------------------------------------ cast
def _cast_view(p: Project, entry: dict) -> dict:
    previews = sorted((p.root / "previews").glob(f"{entry['id']}_*.png"), key=lambda f: f.stat().st_mtime)
    return {**entry, "_preview": file_url(p, previews[-1]) if previews else None}


@router.get("/series/{sid}/cast")
def list_cast(sid: str):
    p = _project(sid)
    return [_cast_view(p, e) for e in p.cast().values()]


@router.get("/series/{sid}/cast/{cid}")
def get_cast(sid: str, cid: str):
    p = _project(sid)
    path = p.root / "cast" / f"{cid}.yaml"
    if not ID_RE.match(cid) or not path.is_file():
        raise HTTPException(404, f"unknown character '{cid}'")
    return _cast_view(p, read_yaml(path))


@router.put("/series/{sid}/cast/{cid}")
def put_cast(sid: str, cid: str, entry: dict = Body(...)):
    p = _project(sid)
    entry = {k: v for k, v in entry.items() if not k.startswith("_")}
    if entry.get("id") != cid or not ID_RE.match(cid):
        raise HTTPException(422, {"errors": [f"id must be '{cid}'"]})
    try:
        p.save_cast_member(entry)
    except ValidationFailed as exc:
        raise HTTPException(422, {"errors": exc.errors}) from exc
    return _cast_view(p, entry)


@router.post("/series/{sid}/cast")
def create_cast(sid: str, payload: dict = Body(...)):
    p = _project(sid)
    cid = payload.get("id", "")
    if not ID_RE.match(cid):
        raise HTTPException(422, {"errors": ["id must be lowercase letters, digits and _ (start with a letter)"]})
    if (p.root / "cast" / f"{cid}.yaml").exists():
        raise HTTPException(409, f"character '{cid}' already exists")
    base = copy.deepcopy(next(iter(p.cast().values()), None))
    if base is None:
        raise HTTPException(400, "no template character in this series")
    entry = {**base, "id": cid, "name": payload.get("name") or cid.title(), "kind": payload.get("kind", "procedural")}
    if entry["kind"] == "imported":
        entry["import"] = {"file": payload.get("file"), "bone_map": {}, "face": {}}
    else:
        entry.pop("import", None)
    try:
        p.save_cast_member(entry)
    except ValidationFailed as exc:
        raise HTTPException(422, {"errors": exc.errors}) from exc
    return _cast_view(p, entry)


@router.delete("/series/{sid}/cast/{cid}")
def delete_cast(sid: str, cid: str):
    p = _project(sid)
    used = [c["id"] for c in p.bible().get("characters", []) if c.get("id") == cid]
    if used:
        raise HTTPException(409, f"'{cid}' is a character of the bible; remove it there first")
    (p.root / "cast" / f"{cid}.yaml").unlink(missing_ok=True)
    return {"ok": True}


@router.post("/series/{sid}/cast/{cid}/preview")
def preview_cast(sid: str, cid: str, payload: dict = Body(default={})):
    _project(sid)
    params = {"series": sid, "character": cid, "turntable": int(payload.get("turntable", 0))}
    if payload.get("cast"):
        params["cast"] = {k: v for k, v in payload["cast"].items() if not k.startswith("_")}
    return _submit("preview_character", params)


# ------------------------------------------------------------------ uploads (characters, mocap, sfx, music)
@router.post("/series/{sid}/uploads/{kind}")
async def upload(sid: str, kind: str, file: UploadFile = File(...), license: str = Form(""), source: str = Form(""),
                 tags: str = Form("")):
    p = _project(sid)
    if kind not in UPLOAD_KINDS:
        raise HTTPException(400, f"unknown upload kind '{kind}'")
    name = Path(file.filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in UPLOAD_KINDS[kind]:
        raise HTTPException(400, f"{kind} files must be one of {sorted(UPLOAD_KINDS[kind])}")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    dest_dir = p.root / "characters" if kind == "character" else ASSETS_DIR / {"animation": "animations"}.get(kind, kind)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe
    with open(dest, "wb") as fh:
        shutil.copyfileobj(file.file, fh)
    # record source + license in the folder's manifest (third-party files are never committed)
    manifest = dest_dir / "license_manifest.yaml"
    key = {"character": "characters", "animation": "clips", "sfx": "sounds", "music": "tracks"}[kind]
    doc = read_yaml(manifest, {}) if manifest.is_file() else {}
    doc = doc or {}
    entries = [e for e in (doc.get(key) or []) if isinstance(e, dict) and e.get("file") != safe]
    entry = {"file": safe, "license": license or "unknown - fill in", "source": source or "uploaded in the web UI"}
    if tags.strip():
        entry["moods" if kind == "music" else "tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    entries.append(entry)
    doc[key] = entries
    if manifest.is_file():
        header = "".join(line for line in manifest.read_text(encoding="utf-8").splitlines(True) if line.startswith("#"))
        manifest.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    else:
        write_yaml(manifest, doc)
    return {"file": safe, "path": str(dest), "kind": kind}


@router.post("/series/{sid}/characters/inspect")
def inspect_character(sid: str, payload: dict = Body(...)):
    _project(sid)
    return _submit("inspect_character", {"series": sid, "file": payload["file"]})


# ------------------------------------------------------------------ arcs
@router.get("/series/{sid}/arcs")
def list_arcs(sid: str):
    return _project(sid).arcs()


@router.get("/series/{sid}/arcs/{aid}")
def get_arc(sid: str, aid: str):
    arc = _project(sid).arc(aid)
    if arc is None:
        raise HTTPException(404, f"unknown arc '{aid}'")
    return arc


@router.put("/series/{sid}/arcs/{aid}")
def put_arc(sid: str, aid: str, arc: dict = Body(...)):
    from storyforge.story.arc import arc_semantic_errors, normalize_arc

    p = _project(sid)
    if p.arc(aid) is None:
        raise HTTPException(404, f"unknown arc '{aid}'")
    arc["arc_id"] = aid
    arc = normalize_arc(arc, arc.get("idea", ""))
    b = p.bible()
    errors = schema_errors("arc", arc) or arc_semantic_errors(
        arc, len(arc.get("parts", [])), {c["id"] for c in b.get("characters", [])},
        {loc["id"] for loc in b.get("locations", [])})
    if errors:
        raise HTTPException(422, {"errors": errors})
    p.save_arc(arc)
    p.create_arc_episodes(arc)
    return arc


@router.delete("/series/{sid}/arcs/{aid}")
def delete_arc(sid: str, aid: str):
    p = _project(sid)
    try:
        p.delete_arc(aid)
    except KeyError as exc:
        raise HTTPException(404, f"unknown arc '{aid}'") from exc
    return {"ok": True}


@router.post("/series/{sid}/arcs/plan")
def plan_arc(sid: str, payload: dict = Body(...)):
    _project(sid)
    idea = (payload.get("idea") or "").strip()
    if len(idea) < 8:
        raise HTTPException(422, {"errors": ["describe the idea in a sentence or two"]})
    parts = int(payload.get("parts", 2))
    if not 2 <= parts <= 5:
        raise HTTPException(422, {"errors": ["an arc has 2 to 5 parts"]})
    return _submit("plan_arc", {"series": sid, "idea": idea[:1000], "parts": parts,
                                "variation": int(payload.get("variation", 0))})


@router.post("/series/{sid}/arcs/{aid}/run")
def run_arc(sid: str, aid: str, payload: dict = Body(default={})):
    p = _project(sid)
    if p.arc(aid) is None:
        raise HTTPException(404, f"unknown arc '{aid}'")
    params = {"series": sid, "arc": aid, **{k: payload[k] for k in ("preset", "until", "parts", "autofix",
                                                                     "ignore_gates", "force") if k in payload}}
    return _submit("run_arc", params)


# ------------------------------------------------------------------ episodes
def _episode_summary(p: Project, meta: dict) -> dict:
    d = p.root / "episodes" / meta["id"]
    outputs = {}
    for preset in ("proxy", "draft", "final", "final_4k"):
        v = d / "output" / f"{meta['id']}_{preset}.mp4"
        if v.is_file():
            q = read_json(d / "quality" / f"report_{preset}.json", None)
            outputs[preset] = {"video": file_url(p, v), "clean": file_url(p, d / "output" / f"{meta['id']}_{preset}_clean.mp4"),
                               "quality": q.get("passed") if q else None}
    cont = read_json(d / "continuity.json", None)
    return {**meta, "outputs": outputs, "has_screenplay": (d / "screenplay.json").is_file(),
            "reviewed": (d / "screenplay.final.json").is_file(),
            "continuity": cont.get("counts") if cont else None,
            "storyboard": (d / "storyboard" / "index.json").is_file()}


@router.get("/series/{sid}/episodes")
def list_episodes(sid: str):
    p = _project(sid)
    return [_episode_summary(p, m) for m in p.episodes()]


@router.get("/series/{sid}/episodes/{eid}")
def get_episode(sid: str, eid: str):
    p = _project(sid)
    d = _episode(p, eid)
    meta = p.episode_meta(eid)
    from storyforge.jobs.handlers import episode_outputs

    files = episode_outputs(p, eid)
    for f in files:
        f["url"] = file_url(p, p.root / f["path"])
    return {**_episode_summary(p, meta), "stages": _stage_records(d), "files": files,
            "jobs": get_manager().store.list(series=sid, episode=eid, limit=10)}


@router.get("/series/{sid}/episodes/{eid}/screenplay")
def get_screenplay(sid: str, eid: str):
    p = _project(sid)
    d = _episode(p, eid)
    return {"draft": read_json(d / "screenplay.json", None), "reviewed": read_json(d / "screenplay.reviewed.json", None),
            "final": read_json(d / "screenplay.final.json", None), "edits": read_json(d / "edits.json", {}),
            "review": read_json(d / "review.json", None), "continuity": read_json(d / "continuity.json", None),
            "continuity_entry": read_json(d / "continuity_entry.json", None)}


@router.put("/series/{sid}/episodes/{eid}/screenplay")
def put_screenplay(sid: str, eid: str, edited: dict = Body(...)):
    """Beat editor save: the full edited screenplay -> edits.json (diff against the reviewed script)."""
    from storyforge.story.screenplay_tools import apply_edits, diff_edits, normalize, semantic_errors

    p = _project(sid)
    d = _episode(p, eid)
    base = read_json(d / "screenplay.reviewed.json", None) or read_json(d / "screenplay.json", None)
    if base is None:
        raise HTTPException(409, "this episode has no screenplay yet; write it first")
    edits = diff_edits(base, edited)
    final = normalize(apply_edits(base, edits))
    b = p.bible()
    errors = schema_errors("screenplay", final) + semantic_errors(final, b, set(p.cast()),
                                                                  {loc["id"] for loc in b.get("locations", [])})
    if errors:
        raise HTTPException(422, {"errors": errors})
    write_json(d / "edits.json", edits)
    return {"edits": edits, "edited_beats": sorted(edits.get("beats", {}))}


@router.delete("/series/{sid}/episodes/{eid}/edits")
def reset_edits(sid: str, eid: str):
    p = _project(sid)
    (_episode(p, eid) / "edits.json").unlink(missing_ok=True)
    return {"ok": True}


@router.post("/series/{sid}/episodes/{eid}/run")
def run_episode(sid: str, eid: str, payload: dict = Body(default={})):
    p = _project(sid)
    _episode(p, eid)
    keys = ("preset", "until", "force", "shots", "regenerate", "autofix", "ignore_gates", "no_render", "max_frames",
            "duration", "fps")
    return _submit("run_episode", {"series": sid, "episode": eid, **{k: payload[k] for k in keys if k in payload}})


@router.get("/series/{sid}/episodes/{eid}/shots")
def get_shots(sid: str, eid: str):
    p = _project(sid)
    d = _episode(p, eid)
    sl = read_json(d / "shotlist.json", None)
    return {"shotlist": sl, "overrides": read_json(d / "shot_overrides.json", {}),
            "auto_overrides": read_json(d / "shot_overrides.auto.json", {}),
            "storyboard": _storyboard(p, d)}


@router.put("/series/{sid}/episodes/{eid}/shots/overrides")
def put_shot_overrides(sid: str, eid: str, overrides: dict = Body(...)):
    from storyforge.models.constants import CAMERA_MOVES, SHOT_TYPES

    p = _project(sid)
    d = _episode(p, eid)
    sl = read_json(d / "shotlist.json", {"shots": []})
    ids = {s["id"] for s in sl.get("shots", [])}
    cast = set(read_json(d / "timeline.json", {}).get("cast", []))
    errors, clean = [], {}
    for sid_, ov in overrides.items():
        if sid_ not in ids:
            errors.append(f"unknown shot '{sid_}'")
            continue
        o = {}
        if ov.get("type"):
            if ov["type"] not in SHOT_TYPES:
                errors.append(f"{sid_}: unknown shot type {ov['type']}")
            o["type"] = ov["type"]
        if ov.get("movement"):
            if ov["movement"] not in CAMERA_MOVES + ["static"]:
                errors.append(f"{sid_}: unknown camera move {ov['movement']}")
            o["movement"] = ov["movement"]
            if ov.get("movement_amount") is not None:
                o["movement_amount"] = max(0.0, min(2.0, float(ov["movement_amount"])))
        if ov.get("lens_mm"):
            o["lens_mm"] = max(12.0, min(200.0, float(ov["lens_mm"])))
        if ov.get("fstop"):
            o["fstop"] = max(0.95, min(22.0, float(ov["fstop"])))
        if ov.get("subject"):
            if ov["subject"] not in cast:
                errors.append(f"{sid_}: '{ov['subject']}' is not in this episode's cast")
            o["subject"] = ov["subject"]
        if ov.get("framing"):
            o["framing"] = ov["framing"]
        if o:
            clean[sid_] = o
    if errors:
        raise HTTPException(422, {"errors": errors})
    write_json(d / "shot_overrides.json", clean)
    return {"overrides": clean}


@router.post("/series/{sid}/episodes/{eid}/shots/{shot}/rerender")
def rerender_shot(sid: str, eid: str, shot: str, payload: dict = Body(default={})):
    p = _project(sid)
    _episode(p, eid)
    params = {"series": sid, "episode": eid, "shots": [shot], "rerender_shots": [shot],
              "preset": payload.get("preset") or "draft"}
    return _submit("run_episode", params)


def _storyboard(p: Project, d: Path) -> dict | None:
    idx = read_json(d / "storyboard" / "index.json", None)
    if not idx:
        return None
    for s in idx.get("shots", []):
        s["url"] = file_url(p, d / s["image"])
    return idx


@router.get("/series/{sid}/episodes/{eid}/storyboard")
def get_storyboard(sid: str, eid: str):
    p = _project(sid)
    return _storyboard(p, _episode(p, eid)) or {"shots": []}


@router.post("/series/{sid}/episodes/{eid}/storyboard")
def make_storyboard(sid: str, eid: str):
    p = _project(sid)
    _episode(p, eid)
    return _submit("storyboard", {"series": sid, "episode": eid})


@router.get("/series/{sid}/episodes/{eid}/timeline")
def get_timeline(sid: str, eid: str):
    p = _project(sid)
    d = _episode(p, eid)
    tl = read_json(d / "timeline.json", None)
    if tl is None:
        raise HTTPException(409, "no timeline yet; run the episode first")
    sl = read_json(d / "shotlist.json", {"shots": []})
    mix = read_json(d / "audio" / "mix_stats.json", {})
    lead = float(mix.get("lead_seconds", 0.0) or 0.0)
    beats = [{k: b.get(k) for k in ("id", "start", "end", "speaker", "addressee", "line", "action", "emotion",
                                    "beat_type", "words")} for b in tl.get("beats", [])]
    shots = [{k: s.get(k) for k in ("id", "type", "subject", "start", "end", "beat", "lens_mm")} |
             {"movement": (s.get("movement") or {}).get("type")} for s in sl.get("shots", [])]
    return {"duration": tl["duration"], "fps": tl["fps"], "lead_seconds": lead, "cast": tl.get("cast", []),
            "beats": beats, "shots": shots, "location": tl.get("location")}


@router.get("/series/{sid}/episodes/{eid}/quality")
def get_quality(sid: str, eid: str, preset: str | None = Query(None)):
    p = _project(sid)
    d = _episode(p, eid)
    reports = {}
    for f in sorted((d / "quality").glob("report_*.json")):
        reports[f.stem.replace("report_", "")] = read_json(f)
    pre = {f.stem.replace("preflight_", ""): read_json(f) for f in sorted((d / "quality").glob("preflight_*.json"))}
    chosen = preset or next((x for x in ("final_4k", "final", "draft", "proxy") if x in reports), None)
    return {"preset": chosen, "report": reports.get(chosen) if chosen else None, "reports": reports,
            "preflight": pre, "continuity": read_json(d / "continuity.json", None)}


@router.get("/series/{sid}/episodes/{eid}/llm")
def get_llm_calls(sid: str, eid: str):
    p = _project(sid)
    f = _episode(p, eid) / "llm_calls.jsonl"
    if not f.is_file():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()][-200:]


# ------------------------------------------------------------------ files (inside a project only)
@router.get("/files/{sid}/{path:path}")
def get_file(sid: str, path: str):
    p = _project(sid)
    root = p.root.resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(target)


# ------------------------------------------------------------------ jobs
@router.get("/jobs")
def list_jobs(series: str | None = None, episode: str | None = None, status: str | None = None, limit: int = 100):
    return get_manager().store.list(series=series, episode=episode, status=status, limit=min(500, limit))


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = get_manager().store.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return job


@router.get("/jobs/{job_id}/log")
def get_job_log(job_id: str, offset: int = 0):
    store = get_manager().store
    if not store.get(job_id):
        raise HTTPException(404, "unknown job")
    text, nxt = store.read_log(job_id, offset)
    return {"text": text, "offset": nxt}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not get_manager().cancel(job_id):
        raise HTTPException(409, "job is not running or queued")
    return {"ok": True}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str):
    try:
        return get_manager().retry(job_id)
    except KeyError as exc:
        raise HTTPException(404, "unknown job") from exc


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    store = get_manager().store
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "cancel the job first")
    store.delete(job_id)
    return {"ok": True}
