#!/usr/bin/env python3
"""Download the optional local tools StoryForge uses into ./tools (Windows, Linux, macOS).

    python scripts/install_tools.py                  # Rhubarb Lip Sync + the sample cast's Piper voices
    python scripts/install_tools.py --voices en_US-amy-medium en_GB-alba-medium
    python scripts/install_tools.py --no-rhubarb --list

* Rhubarb Lip Sync (MIT) -> tools/rhubarb/   (frame-accurate mouth shapes A-H, X)
* Piper voices (each voice has its own license, see its MODEL_CARD) -> tools/piper_voices/
  Piper itself is installed with `pip install piper-tts` (no binary needed).

Blender and ffmpeg are big system installs: the script only checks for them and prints the
command for your platform. Nothing here is committed to git (tools/ is ignored).
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
RHUBARB_VERSION = "1.14.0"
RHUBARB_URL = ("https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v{v}/"
               "Rhubarb-Lip-Sync-{v}-{os}.zip")
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{family}/{lang}/{name}/{quality}/{voice}{ext}"
SAMPLE_VOICES = ["en_US-ryan-high", "en_US-lessac-medium", "en_US-danny-low", "en_US-amy-low"]


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "storyforge-install-tools"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as fh:
        shutil.copyfileobj(r, fh)
    return dest


def install_rhubarb(force: bool = False) -> None:
    target = TOOLS / "rhubarb"
    exe = target / ("rhubarb.exe" if platform.system() == "Windows" else "rhubarb")
    if exe.is_file() and not force:
        print(f"Rhubarb already installed: {exe}")
        return
    os_name = {"Windows": "Windows", "Darwin": "macOS"}.get(platform.system(), "Linux")
    with tempfile.TemporaryDirectory() as tmp:
        z = _download(RHUBARB_URL.format(v=RHUBARB_VERSION, os=os_name), Path(tmp) / "rhubarb.zip")
        with zipfile.ZipFile(z) as zf:
            for member in zf.namelist():  # never extract outside the temp folder
                if member.startswith("/") or ".." in Path(member).parts:
                    raise RuntimeError(f"unsafe path in archive: {member}")
            zf.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if not roots:
            raise RuntimeError("unexpected Rhubarb archive layout")
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(roots[0]), target)  # keeps the res/ folder next to the executable
    if platform.system() != "Windows":
        exe.chmod(0o755)
    print(f"Rhubarb {RHUBARB_VERSION} -> {exe}")


def voice_url(voice: str, ext: str) -> str:
    lang, name, quality = voice.split("-", 2)
    return VOICE_URL.format(family=lang.split("_")[0], lang=lang, name=name, quality=quality, voice=voice, ext=ext)


def install_voices(voices: list[str], force: bool = False) -> None:
    d = TOOLS / "piper_voices"
    d.mkdir(parents=True, exist_ok=True)
    for v in voices:
        onnx, cfg = d / f"{v}.onnx", d / f"{v}.onnx.json"
        if onnx.is_file() and cfg.is_file() and not force:
            print(f"voice {v}: already installed")
            continue
        try:
            _download(voice_url(v, ".onnx.json"), cfg)
            _download(voice_url(v, ".onnx"), onnx)
            json.loads(cfg.read_text(encoding="utf-8"))
            print(f"voice {v} -> {onnx}")
        except Exception as exc:  # keep going with the other voices
            onnx.unlink(missing_ok=True)
            cfg.unlink(missing_ok=True)
            print(f"voice {v}: FAILED ({exc}). Voice names look like en_US-ryan-high; browse "
                  "https://huggingface.co/rhasspy/piper-voices", file=sys.stderr)


def check_system_tools() -> None:
    system = platform.system()
    hints = {
        "Windows": {"blender": "winget install BlenderFoundation.Blender   (then set BLENDER_PATH in .env)",
                    "ffmpeg": "winget install Gyan.FFmpeg"},
        "Darwin": {"blender": "brew install --cask blender", "ffmpeg": "brew install ffmpeg"},
    }.get(system, {"blender": "download the Linux build from https://www.blender.org/download/ (or snap install blender)",
                   "ffmpeg": "sudo apt install ffmpeg   (or your distribution's package manager)"})
    sys.path.insert(0, str(ROOT))
    try:
        from storyforge.config import get_settings

        s = get_settings()
        found = {"blender": s.tool("blender") or (s.blender_python and "bpy"), "ffmpeg": s.tool("ffmpeg")}
    except Exception:
        found = {"blender": shutil.which("blender"), "ffmpeg": shutil.which("ffmpeg")}
    for tool, where in found.items():
        print(f"{tool}: {where}" if where else f"{tool}: NOT FOUND -> {hints[tool]}")
    try:
        import piper  # noqa: F401

        print("piper: python package installed")
    except ImportError:
        print("piper: not installed -> pip install piper-tts   (offline voices; optional)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voices", nargs="*", default=None, help="Piper voices to install (default: the sample cast's)")
    ap.add_argument("--no-rhubarb", action="store_true")
    ap.add_argument("--no-voices", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    ap.add_argument("--list", action="store_true", help="only report what is installed")
    a = ap.parse_args()
    check_system_tools()
    if a.list:
        return 0
    if not a.no_rhubarb:
        try:
            install_rhubarb(a.force)
        except Exception as exc:
            print(f"Rhubarb: FAILED ({exc}); download it from https://github.com/DanielSWolf/rhubarb-lip-sync/releases "
                  "and set RHUBARB_PATH in .env", file=sys.stderr)
    if not a.no_voices:
        install_voices(a.voices if a.voices else SAMPLE_VOICES, a.force)
    print("Done. Run `storyforge doctor --quick` to see what StoryForge detects.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
