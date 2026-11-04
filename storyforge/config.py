"""Runtime configuration.

Settings come from environment variables, optionally loaded from a `.env` file in the
repository root (or the current directory). Every external tool is discovered with the
same precedence: explicit env var -> repo `tools/` folder -> PATH -> well-known install
locations (Windows/macOS/Linux). Nothing here raises when a tool is missing: callers ask
`settings.tool("blender")` and get `None`, so every stage can degrade gracefully.
"""

from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = REPO_ROOT / "assets"
BLENDER_PKG_DIR = REPO_ROOT / "storyforge_blender"
TOOLS_DIR = REPO_ROOT / "tools"
IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
EXE = ".exe" if IS_WINDOWS else ""


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a hard dependency
        return
    for candidate in (Path.cwd() / ".env", REPO_ROOT / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip().strip('"').strip("'")
    return value if value else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return _env(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


def _version_key(path: str) -> tuple:
    nums = re.findall(r"\d+", path)
    return tuple(int(n) for n in nums[-3:]) if nums else (0,)


def _candidates_blender() -> list[str]:
    if IS_WINDOWS:
        pats = [
            r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blender Foundation\Blender*\blender.exe"),
            r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
        ]
    elif IS_MAC:
        pats = ["/Applications/Blender*.app/Contents/MacOS/Blender"]
    else:
        pats = ["/opt/blender*/blender", "/usr/local/blender*/blender", os.path.expanduser("~/blender*/blender"),
                "/snap/bin/blender"]
    found: list[str] = []
    for pat in pats:
        found.extend(glob.glob(pat))
    return sorted(found, key=_version_key, reverse=True)


TOOL_SPECS: dict[str, dict] = {
    "blender": {"env": "BLENDER_PATH", "names": ["blender"], "tools": ["blender/blender"],
                "extra": _candidates_blender},
    "ffmpeg": {"env": "FFMPEG_PATH", "names": ["ffmpeg"], "tools": ["ffmpeg/ffmpeg", "ffmpeg/bin/ffmpeg"]},
    "ffprobe": {"env": "FFPROBE_PATH", "names": ["ffprobe"], "tools": ["ffmpeg/ffprobe", "ffmpeg/bin/ffprobe"]},
    "rhubarb": {"env": "RHUBARB_PATH", "names": ["rhubarb"], "tools": ["rhubarb/rhubarb"]},
    "piper": {"env": "PIPER_PATH", "names": ["piper"], "tools": ["piper/piper"]},
    "espeak": {"env": "ESPEAK_PATH", "names": ["espeak-ng", "espeak"], "tools": ["espeak-ng/espeak-ng"],
               "extra": lambda: [r"C:\Program Files\eSpeak NG\espeak-ng.exe"] if IS_WINDOWS else []},
}


def find_tool(name: str) -> str | None:
    spec = TOOL_SPECS[name]
    explicit = _env(spec["env"])
    if explicit:
        p = Path(os.path.expandvars(os.path.expanduser(explicit)))
        if p.is_file():
            return str(p)
        if p.is_dir():  # allow pointing at the folder
            for n in spec["names"]:
                q = p / f"{n}{EXE}"
                if q.is_file():
                    return str(q)
        return None  # explicit but wrong: do not silently use something else
    for rel in spec.get("tools", []):
        q = TOOLS_DIR / f"{rel}{EXE}"
        if q.is_file():
            return str(q)
    for n in spec["names"]:
        w = shutil.which(n)
        if w:
            return w
    extra = spec.get("extra")
    if extra:
        for c in extra():
            if Path(c).is_file():
                return c
    return None


@dataclass
class Settings:
    data_dir: Path
    demo_forced: bool
    llm_provider: str
    anthropic_api_key: str
    anthropic_model: str
    anthropic_effort: str
    anthropic_fallbacks: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    openai_reasoning_effort: str
    llm_max_attempts: int
    tts_provider: str
    elevenlabs_api_key: str
    elevenlabs_model: str
    openai_tts_model: str
    piper_voices_dir: Path
    alignment_mode: str
    whisper_local_model: str
    blender_python: str
    render_device: str
    render_workers: int
    render_preset: str
    render_fps: int
    blender_timeout: int
    host: str
    port: int
    server_workers: int
    _tool_cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls) -> Settings:
        _load_dotenv()
        data_dir = Path(_env("STORYFORGE_DATA_DIR", str(REPO_ROOT / "data")))
        if not data_dir.is_absolute():
            data_dir = (REPO_ROOT / data_dir).resolve()
        voices = _env("PIPER_VOICES_DIR", str(TOOLS_DIR / "piper_voices"))
        return cls(
            data_dir=data_dir,
            demo_forced=_env_bool("STORYFORGE_DEMO", False),
            llm_provider=_env("LLM_PROVIDER", "auto").lower(),
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            anthropic_model=_env("ANTHROPIC_MODEL", "claude-opus-5-5"),
            anthropic_effort=_env("ANTHROPIC_EFFORT", "high"),
            anthropic_fallbacks=_env("ANTHROPIC_FALLBACKS", "default"),
            openai_api_key=_env("OPENAI_API_KEY"),
            openai_model=_env("OPENAI_MODEL", "gpt-5.5"),
            openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_reasoning_effort=_env("OPENAI_REASONING_EFFORT", "").lower(),
            llm_max_attempts=max(1, _env_int("LLM_MAX_ATTEMPTS", 4)),
            tts_provider=_env("TTS_PROVIDER", "auto").lower(),
            elevenlabs_api_key=_env("ELEVENLABS_API_KEY"),
            elevenlabs_model=_env("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
            openai_tts_model=_env("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
            piper_voices_dir=Path(voices),
            alignment_mode=_env("ALIGNMENT_MODE", "auto").lower(),
            whisper_local_model=_env("WHISPER_LOCAL_MODEL", "base.en"),
            blender_python=_env("BLENDER_PYTHON"),
            render_device=_env("RENDER_DEVICE", "auto").upper(),
            render_workers=max(1, _env_int("RENDER_WORKERS", 1)),
            render_preset=_env("RENDER_PRESET", "draft").lower(),
            render_fps=_env_int("RENDER_FPS", 30),
            blender_timeout=_env_int("BLENDER_TIMEOUT", 7200),
            host=_env("STORYFORGE_HOST", "127.0.0.1"),
            port=_env_int("STORYFORGE_PORT", 8000),
            server_workers=max(1, _env_int("STORYFORGE_WORKERS", 1)),
        )

    # -- tools -------------------------------------------------------------------
    def tool(self, name: str) -> str | None:
        if name not in self._tool_cache:
            self._tool_cache[name] = find_tool(name)
        return self._tool_cache[name]

    def blender_command(self) -> list[str] | None:
        """Command prefix that runs a StoryForge Blender script.

        Real Blender: ``blender -b --factory-startup --python-exit-code 1 -P <script> -- args``
        bpy-module Python (dev/CI): ``python <script> -- args``.
        Returned as a prefix; the caller appends the script and its args via
        :func:`storyforge.render.blender.blender_invocation`.
        """
        exe = self.tool("blender")
        if exe:
            return [exe]
        if self.blender_python and Path(self.blender_python).is_file():
            return [self.blender_python]
        return None

    @property
    def blender_mode(self) -> str | None:
        if self.tool("blender"):
            return "blender"
        if self.blender_python and Path(self.blender_python).is_file():
            return "bpy"
        return None

    # -- providers -----------------------------------------------------------------
    @property
    def demo_mode(self) -> bool:
        if self.demo_forced or self.llm_provider == "demo":
            return True
        return not (self.anthropic_api_key or self.openai_api_key)

    def resolved_llm_provider(self) -> str:
        if self.demo_forced:
            return "demo"
        p = self.llm_provider
        if p == "anthropic" and self.anthropic_api_key:
            return "anthropic"
        if p == "openai" and self.openai_api_key:
            return "openai"
        if p in {"auto", "anthropic", "openai"}:
            if self.anthropic_api_key:
                return "anthropic"
            if self.openai_api_key:
                return "openai"
        return "demo"

    def summary(self) -> dict:
        return {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "data_dir": str(self.data_dir),
            "llm_provider": self.resolved_llm_provider(),
            "tts_provider": self.tts_provider,
            "blender": self.tool("blender") or (f"bpy via {self.blender_python}" if self.blender_mode == "bpy" else None),
            "ffmpeg": self.tool("ffmpeg"),
            "ffprobe": self.tool("ffprobe"),
            "rhubarb": self.tool("rhubarb"),
            "piper": self.tool("piper") or ("python package" if _has_module("piper") else None),
            "piper_voices_dir": str(self.piper_voices_dir),
            "espeak": self.tool("espeak"),
            "render_device": self.render_device,
            "render_workers": self.render_workers,
            "demo_mode": self.demo_mode,
        }


def _has_module(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.load()


def reset_settings() -> None:
    get_settings.cache_clear()
