"""Animation library: built-in procedural clips + user motion capture (assets/animations).

User clips (Mixamo FBX you download yourself, CMU BVH, any glTF) are never committed: drop the
files into assets/animations/ and list them in assets/animations/license_manifest.yaml (source,
license, tags). Each file is retargeted once in Blender onto the canonical clip format and cached
by content hash in $DATA/cache/clips/. When a mocap clip carries a tag (e.g. "wave"), it replaces
the procedural clip with that tag.
"""

from __future__ import annotations

import re
from pathlib import Path

from storyforge.animation.procedural import builtin_clips
from storyforge.config import ASSETS_DIR, BLENDER_PKG_DIR, get_settings
from storyforge.pipeline.cache import ItemCache
from storyforge.util.hashing import file_hash, stable_hash, tree_hash
from storyforge.util.io import read_json, read_yaml, write_json

ANIM_DIR = ASSETS_DIR / "animations"
MOCAP_EXT = {".bvh", ".fbx", ".glb", ".gltf"}

# filename keywords -> tags (Mixamo-style names like "Waving.fbx", "Standing Idle.fbx")
NAME_TAGS = [
    (r"wav(e|ing)", "wave"), (r"point", "point"), (r"shrug", "shrug"), (r"nod", "nod"), (r"head.?shake|no\b", "head_shake"),
    (r"hips|hands.?on", "hands_on_hips"), (r"cross", "cross_arms"), (r"face.?palm", "facepalm"), (r"cheer|victory", "cheer"),
    (r"jump", "jump"), (r"gasp|surprise|shock", "gasp"), (r"laugh", "laugh"), (r"cry|sad", "cry"), (r"think", "think"),
    (r"look.?around|looking", "look_around"), (r"thumb", "thumbs_up"), (r"scratch", "scratch_head"), (r"clap", "clap"),
    (r"bow", "bow"), (r"pick.?up|picking", "pick_up"), (r"talk|convers|explain", "talk"), (r"walk", "walk"),
    (r"run", "run"), (r"sneak|tiptoe|creep", "tiptoe"), (r"idle|breath", "idle"), (r"shiver|cold", "shiver"),
    (r"recoil|flinch", "recoil"), (r"give|hand.?over", "give"),
]


def tags_from_name(name: str) -> list[str]:
    n = name.lower()
    return [tag for pat, tag in NAME_TAGS if re.search(pat, n)]


def manifest() -> dict:
    data = read_yaml(ANIM_DIR / "license_manifest.yaml", {}) or {}
    return {e["file"]: e for e in (data.get("clips") or []) if isinstance(e, dict) and e.get("file")}


def mocap_files() -> list[Path]:
    if not ANIM_DIR.is_dir():
        return []
    return sorted(p for p in ANIM_DIR.rglob("*") if p.suffix.lower() in MOCAP_EXT and p.is_file())


def retarget_code_hash() -> str:
    return tree_hash(BLENDER_PKG_DIR, ["retarget.py", "bonemap.py"])


def load_mocap_clip(path: Path, entry: dict | None = None, log=print) -> dict | None:
    """Retarget (or fetch from cache) one mocap file. Requires Blender."""
    from storyforge.render.blender import BlenderUnavailable, run_blender

    settings = get_settings()
    cache = ItemCache(settings.data_dir / "cache" / "clips")
    bone_map = (entry or {}).get("bone_map")
    key = stable_hash("clip", file_hash(path), retarget_code_hash(), bone_map)
    hit = cache.get(key, ".json")
    if hit:
        return read_json(hit)
    args = ["--file", str(path), "--out", str(cache.path(key, ".json"))]
    if bone_map:
        mp = cache.path(key, ".map.json")
        write_json(mp, bone_map)
        args += ["--map", str(mp)]
    try:
        run_blender(settings, "import-clip", args, on_log=log, timeout=900)
    except BlenderUnavailable:
        return None
    except Exception as exc:  # a broken file must not break the episode
        log(f"mocap import failed for {path.name}: {exc}")
        return None
    clip = read_json(cache.path(key, ".json"))
    tags = list((entry or {}).get("tags") or []) or tags_from_name(path.stem)
    clip["tags"] = sorted(set(tags + clip.get("tags", [])))
    clip["license"] = (entry or {}).get("license", "unknown - add it to license_manifest.yaml")
    clip["category"] = "locomotion" if any(t in ("walk", "run", "tiptoe") for t in tags) else (
        "idle" if "idle" in tags else "gesture")
    clip["loop"] = clip["category"] in ("locomotion", "idle")
    write_json(cache.path(key, ".json"), clip)
    return clip


class ClipLibrary:
    def __init__(self, fps: int, use_mocap: bool = True, log=print):
        self.fps = fps
        self.builtin = builtin_clips(fps)
        self.mocap: dict[str, dict] = {}
        self.log = log
        if use_mocap:
            entries = manifest()
            for p in mocap_files():
                rel = p.relative_to(ANIM_DIR).as_posix()
                entry = entries.get(rel) or entries.get(p.name)
                if entry and str(entry.get("enabled", True)).lower() in ("false", "0", "no"):
                    continue
                clip = load_mocap_clip(p, entry, log)
                if clip:
                    if clip["fps"] != fps:
                        clip = resample(clip, fps)
                    self.mocap[clip["name"]] = clip

    def by_tag(self, tag: str) -> dict | None:
        for c in self.mocap.values():
            if tag in c.get("tags", []):
                return c
        return self.builtin.get(tag) or next((c for c in self.builtin.values() if tag in c.get("tags", [])), None)

    def get(self, name: str) -> dict | None:
        return self.mocap.get(name) or self.builtin.get(name) or self.by_tag(name)

    def index(self) -> list[dict]:
        rows = []
        for c in list(self.builtin.values()) + list(self.mocap.values()):
            rows.append({"name": c["name"], "tags": c.get("tags", []), "frames": c["frames"], "fps": c["fps"],
                         "category": c.get("category"), "source": c.get("source"), "license": c.get("license")})
        return rows


def resample(clip: dict, fps: int) -> dict:
    """Nearest-frame resample (clips are dense, so this is adequate between 24/25/30/60 fps)."""
    from storyforge.animation import quat as Q

    src_fps = clip["fps"]
    n_src = clip["frames"]
    n = max(2, int(round(n_src * fps / src_fps)))
    out = dict(clip)
    out["fps"] = fps
    out["frames"] = n
    bones = {}
    for b, seq in clip["bones"].items():
        res = []
        for i in range(n):
            x = i * src_fps / fps
            a = int(x)
            t = x - a
            qa = tuple(seq[min(a, len(seq) - 1)])
            qb = tuple(seq[min(a + 1, len(seq) - 1)])
            res.append(Q.rounded(Q.slerp(qa, qb, t)))
        bones[b] = res
    out["bones"] = bones
    out["root"] = [clip["root"][min(int(i * src_fps / fps), len(clip["root"]) - 1)] for i in range(n)]
    out["contacts"] = {k: [[int(s * fps / src_fps), int(e * fps / src_fps)] for s, e in v]
                       for k, v in clip.get("contacts", {}).items()}
    if clip.get("squash"):
        out["squash"] = [[int(f * fps / src_fps), s] for f, s in clip["squash"]]
    return out


def export_builtin_bvh(target: Path, fps: int = 30) -> list[Path]:
    from storyforge.animation.bvh import write_bvh

    out = []
    for name, clip in builtin_clips(fps).items():
        out.append(write_bvh(clip, target / f"{name}.bvh"))
    return out
