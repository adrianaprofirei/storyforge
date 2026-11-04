"""Series projects on disk.

Layout (under ``$STORYFORGE_DATA_DIR/projects/<series_id>/``)::

    bible/current.yaml            latest bible (what every stage reads)
    bible/versions/v0001.yaml     immutable history, one file per save
    cast/<character_id>.yaml      cast registry entries (look, rig, voice, settings)
    arcs/<arc_id>.json            arc plans
    episodes/<episode_id>/        one folder per part (screenplay, voices, renders, outputs ...)

Everything is plain YAML/JSON so it can be edited by hand, diffed and versioned.
"""

from __future__ import annotations

import copy
import datetime as _dt
import shutil
from pathlib import Path

from storyforge.config import ASSETS_DIR, get_settings
from storyforge.schemas import ValidationFailed, schema_errors
from storyforge.util.io import ensure_dir, read_data, read_json, read_yaml, write_json, write_yaml
from storyforge.util.text import slugify

SAMPLES_DIR = ASSETS_DIR / "samples"


def now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()


class Project:
    def __init__(self, root: Path):
        self.root = Path(root)

    # ------------------------------------------------------------------ discovery
    @staticmethod
    def projects_dir() -> Path:
        return ensure_dir(get_settings().data_dir / "projects")

    @classmethod
    def list(cls) -> list[Project]:
        return [cls(p) for p in sorted(cls.projects_dir().iterdir()) if (p / "bible" / "current.yaml").is_file()]

    @classmethod
    def open(cls, series_id: str) -> Project:
        p = cls(cls.projects_dir() / series_id)
        if not p.bible_path.is_file():
            raise FileNotFoundError(f"no project '{series_id}' in {cls.projects_dir()}")
        return p

    @classmethod
    def create(cls, bible: dict, cast: dict[str, dict] | None = None, overwrite: bool = False) -> Project:
        errors = schema_errors("bible", bible)
        if errors:
            raise ValidationFailed(errors)
        root = cls.projects_dir() / bible["series_id"]
        if root.exists() and overwrite:
            shutil.rmtree(root)
        proj = cls(root)
        ensure_dir(root / "bible" / "versions")
        ensure_dir(root / "cast")
        ensure_dir(root / "arcs")
        ensure_dir(root / "episodes")
        if not proj.bible_path.is_file():
            proj.save_bible(bible, message="created")
        for cid, entry in (cast or {}).items():
            if not (root / "cast" / f"{cid}.yaml").is_file():
                proj.save_cast_member(entry)
        return proj

    @classmethod
    def ensure_demo(cls, reset: bool = False) -> Project:
        """Create (or reuse) the bundled sample series with its 2-part sample arc."""
        bible = read_yaml(SAMPLES_DIR / "bible.yaml")
        cast = read_yaml(SAMPLES_DIR / "cast.yaml")
        proj = cls.create(bible, cast, overwrite=reset)
        arc = read_json(SAMPLES_DIR / "arc.json")
        if proj.arc(arc["arc_id"]) is None:
            proj.save_arc(arc)
            for part in arc["parts"]:
                ep_id = proj.episode_id_for(arc["arc_id"], part["part"])
                sp_src = SAMPLES_DIR / "screenplays" / f"part{part['part']}.json"
                ep_dir = proj.episode_dir(ep_id)
                if sp_src.is_file() and not (ep_dir / "screenplay.json").is_file():
                    sp = read_json(sp_src)
                    sp["episode_id"] = ep_id
                    write_json(ep_dir / "screenplay.json", sp)
                proj.save_episode_meta(ep_id, {"arc_id": arc["arc_id"], "part": part["part"],
                                               "title": part["title"], "status": "written",
                                               "source": "sample"})
            proj.register_arc_in_bible(arc)
        return proj

    # ------------------------------------------------------------------ bible
    @property
    def series_id(self) -> str:
        return self.root.name

    @property
    def bible_path(self) -> Path:
        return self.root / "bible" / "current.yaml"

    def bible(self) -> dict:
        return read_yaml(self.bible_path)

    def bible_versions(self) -> list[dict]:
        out = []
        for p in sorted((self.root / "bible" / "versions").glob("v*.yaml")):
            doc = read_yaml(p)
            out.append({"version": doc.get("version"), "file": p.name,
                        "saved_at": doc.get("_meta", {}).get("saved_at"),
                        "message": doc.get("_meta", {}).get("message", "")})
        return out

    def bible_version(self, version: int) -> dict:
        return read_yaml(self.root / "bible" / "versions" / f"v{version:04d}.yaml")

    def save_bible(self, bible: dict, message: str = "edit") -> int:
        doc = copy.deepcopy(bible)
        doc.pop("_meta", None)
        errors = schema_errors("bible", doc)
        if errors:
            raise ValidationFailed(errors)
        versions = self.bible_versions()
        version = (max((v["version"] or 0) for v in versions) + 1) if versions else 1
        doc["version"] = version
        doc["_meta"] = {"saved_at": now_iso(), "message": message}
        ensure_dir(self.root / "bible" / "versions")
        write_yaml(self.root / "bible" / "versions" / f"v{version:04d}.yaml", doc)
        write_yaml(self.bible_path, doc)
        return version

    def update_bible(self, fn, message: str) -> int:
        bible = self.bible()
        fn(bible)
        return self.save_bible(bible, message=message)

    # ------------------------------------------------------------------ cast
    def cast(self) -> dict[str, dict]:
        out = {}
        for p in sorted((self.root / "cast").glob("*.yaml")):
            entry = read_yaml(p)
            imp = entry.get("import") or {}
            if imp.get("file"):
                entry["import"] = {**imp, "file": str(self.character_file(imp["file"]))}
            out[entry["id"]] = entry
        return out

    def character_file(self, name: str) -> Path:
        """Imported character files: absolute, or relative to <project>/characters or assets/characters."""
        p = Path(name)
        if p.is_absolute():
            return p
        for base in (self.root / "characters", ASSETS_DIR / "characters"):
            if (base / p).exists():
                return (base / p).resolve()
        return (ASSETS_DIR / "characters" / p).resolve()

    def cast_member(self, cid: str) -> dict:
        return read_yaml(self.root / "cast" / f"{cid}.yaml")

    def save_cast_member(self, entry: dict) -> Path:
        errors = schema_errors("cast_member", entry)
        if errors:
            raise ValidationFailed(errors)
        return write_yaml(self.root / "cast" / f"{entry['id']}.yaml", entry)

    # ------------------------------------------------------------------ arcs
    def arcs(self) -> list[dict]:
        return [read_json(p) for p in sorted((self.root / "arcs").glob("*.json"))]

    def arc(self, arc_id: str) -> dict | None:
        p = self.root / "arcs" / f"{arc_id}.json"
        return read_json(p) if p.is_file() else None

    def save_arc(self, arc: dict) -> dict:
        errors = schema_errors("arc", arc)
        if errors:
            raise ValidationFailed(errors)
        if not arc.get("arc_id"):
            base = slugify(arc["title"], 32)
            arc_id, n = base, 2
            while (self.root / "arcs" / f"{arc_id}.json").exists():
                arc_id, n = f"{base}_{n}", n + 1
            arc["arc_id"] = arc_id
        write_json(self.root / "arcs" / f"{arc['arc_id']}.json", arc)
        return arc

    @staticmethod
    def episode_id_for(arc_id: str, part: int) -> str:
        return f"{arc_id}_p{part}"

    def register_arc_in_bible(self, arc: dict) -> None:
        def fn(b):
            arcs = [a for a in b.get("arcs", []) if a.get("id") != arc["arc_id"]]
            arcs.append({"id": arc["arc_id"], "title": arc["title"],
                         "parts": [self.episode_id_for(arc["arc_id"], p["part"]) for p in arc["parts"]],
                         "status": "planned", "final_payoff": arc.get("final_payoff", "")})
            b["arcs"] = arcs
            eps = {e["id"]: e for e in b.get("episodes", [])}
            for p in arc["parts"]:
                eid = self.episode_id_for(arc["arc_id"], p["part"])
                eps.setdefault(eid, {"id": eid, "arc_id": arc["arc_id"], "part": p["part"],
                                     "title": p["title"], "status": "planned"})
            b["episodes"] = list(eps.values())
        self.update_bible(fn, message=f"arc {arc['arc_id']} planned")

    def set_episode_status_in_bible(self, episode_id: str, status: str, **extra) -> None:
        def fn(b):
            for e in b.get("episodes", []):
                if e.get("id") == episode_id:
                    e["status"] = status
                    e.update(extra)
        self.update_bible(fn, message=f"{episode_id}: {status}")

    # ------------------------------------------------------------------ episodes
    def episode_dir(self, episode_id: str) -> Path:
        return ensure_dir(self.root / "episodes" / episode_id)

    def episodes(self) -> list[dict]:
        out = []
        for d in sorted((self.root / "episodes").iterdir()) if (self.root / "episodes").is_dir() else []:
            meta = read_json(d / "episode.json", {})
            meta.setdefault("id", d.name)
            out.append(meta)
        out.sort(key=lambda m: (m.get("arc_id", ""), m.get("part", 0)))
        return out

    def episode_meta(self, episode_id: str) -> dict:
        meta = read_json(self.episode_dir(episode_id) / "episode.json", {})
        meta.setdefault("id", episode_id)
        return meta

    def save_episode_meta(self, episode_id: str, updates: dict) -> dict:
        meta = self.episode_meta(episode_id)
        meta.update(updates)
        meta["updated_at"] = now_iso()
        write_json(self.episode_dir(episode_id) / "episode.json", meta)
        return meta

    def location(self, location_id: str) -> dict:
        for loc in self.bible().get("locations", []):
            if loc["id"] == location_id:
                return loc
        return {"id": location_id, "name": location_id, "preset": location_id}

    def previous_episode(self, episode_id: str) -> str | None:
        meta = self.episode_meta(episode_id)
        if meta.get("part", 1) <= 1 or not meta.get("arc_id"):
            return None
        return self.episode_id_for(meta["arc_id"], meta["part"] - 1)


def load_document(path: Path) -> dict:
    return read_data(path)
