"""Scene build: JSON scene spec -> fully set up Blender scene (+ saved editable .blend)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import bpy

from storyforge_blender import animate
from storyforge_blender.cameras import build_shot_cameras
from storyforge_blender.character import build_character
from storyforge_blender.lighting import build_shot_rig, build_sun, build_world
from storyforge_blender.location import SetBuilder, animate_set
from storyforge_blender.materials import MaterialFactory
from storyforge_blender.render_settings import configure


def log(msg: str) -> None:
    print(f"SF_LOG {msg}", flush=True)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "StoryForge"
    return scene


def build_scene(spec: dict, episode_dir: Path) -> dict:
    t0 = time.time()
    scene = reset_scene()
    fps = int(spec["fps"])
    fs, fe = int(spec["frame_start"]), int(spec["frame_end"])
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.frame_start, scene.frame_end = fs, fe
    scene.unit_settings.system = "METRIC"
    style = spec["style"]["preset"]
    mats = MaterialFactory(style)
    log(f"style={style} frames={fs}-{fe} fps={fps}")

    # set
    loc = spec["location"]
    sb = SetBuilder(scene, mats, loc["preset"], loc["time_of_day"], seed=int(loc.get("seed", 11))).build()
    animate_set(sb, spec.get("events", []), fps, fs, fe)
    log(f"set {sb.preset} built ({len(sb.objects)} objects)")

    # characters
    chars_coll = bpy.data.collections.new("CHARACTERS")
    scene.collection.children.link(chars_coll)
    characters = {}
    for cs in spec["characters"]:
        c = build_character(cs, mats, scene)
        # move the character collection under CHARACTERS (for light linking / line art)
        scene.collection.children.unlink(c["collection"])
        chars_coll.children.link(c["collection"])
        animate.apply_root_path(c["rig"], cs.get("path", []), fs, fps)
        characters[cs["id"]] = c
        log(f"character {cs['id']} built")
    from storyforge_blender import performance

    performance.apply_all(scene, spec, characters, mats, sb)

    # cameras + lighting
    build_shot_cameras(scene, spec["shots"])
    light_coll = bpy.data.collections.new("LIGHTS")
    scene.collection.children.link(light_coll)
    lighting = spec.get("lighting", {})
    build_world(scene, lighting["base"])
    build_sun(scene, lighting["base"], light_coll)
    build_shot_rig(scene, lighting.get("rigs", []), chars_coll, light_coll)

    from storyforge_blender import style as style_mod

    style_mod.apply_style(scene, spec, chars_coll, sb)
    info = configure(scene, spec.get("render", {}).get("preset", "draft"), style, spec.get("render", {}).get("device", "AUTO"),
                     fps, volumetric_night=bool(lighting["base"].get("volumetrics")))
    style_mod.apply_grade(scene, spec.get("grade", {}), style)

    # audio in the sequencer so the .blend plays with the final mix
    mix = spec.get("audio", {}).get("mix")
    if mix and (episode_dir / mix).is_file():
        scene.sequence_editor_create()
        se = scene.sequence_editor
        coll = se.strips if hasattr(se, "strips") else se.sequences
        try:
            coll.new_sound("mix", str(episode_dir / mix), 1, fs)
        except Exception as exc:
            log(f"could not add sound strip: {exc}")
    scene["sf_episode"] = spec.get("episode_id", "")
    scene["sf_spec_version"] = spec.get("version", 1)
    log(f"scene built in {time.time() - t0:.1f}s; render {info}")
    return {"characters": characters, "set": sb, "render": info}


def save_blend(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        bpy.context.preferences.filepaths.save_version = 0  # no .blend1 backups
    except Exception:
        pass
    bpy.ops.wm.save_as_mainfile(filepath=str(path), compress=True, relative_remap=True)
    try:
        bpy.ops.file.make_paths_relative()
        bpy.ops.wm.save_mainfile(filepath=str(path), compress=True)
    except Exception:
        pass


def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def env_flag(name: str) -> bool:
    return os.environ.get(name, "0") in ("1", "true", "yes")
