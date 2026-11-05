"""Offline TTS providers: Piper (neural, good), espeak-ng (robotic, last resort), silent."""

from __future__ import annotations

import importlib.util
import re
import wave
from pathlib import Path

from storyforge.config import Settings
from storyforge.providers.tts.base import TTSError, TTSProvider, VoiceRequest, VoiceResult
from storyforge.util.proc import run

PIPER_PACE = {"slow": 1.18, "normal": 1.0, "fast": 0.86}
ESPEAK_PACE = {"slow": 0.85, "normal": 1.0, "fast": 1.18}


def _norm_voice_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class PiperTTS(TTSProvider):
    """Piper via the `piper` executable (PIPER_PATH) or the `piper-tts` Python package."""

    name = "piper"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.exe = settings.tool("piper")
        self.has_module = importlib.util.find_spec("piper") is not None
        self._voices: dict[str, object] = {}

    def voice_files(self) -> dict[str, Path]:
        d = Path(self.settings.piper_voices_dir)
        out = {}
        if d.is_dir():
            for p in d.rglob("*.onnx"):
                if p.with_suffix(".onnx.json").is_file() or Path(str(p) + ".json").is_file():
                    out[_norm_voice_name(p.stem)] = p
        return out

    def available(self) -> bool:
        return bool((self.exe or self.has_module) and self.voice_files())

    def resolve_model(self, req: VoiceRequest) -> tuple[Path, int | None]:
        files = self.voice_files()
        if not files:
            raise TTSError(f"no Piper voices found in {self.settings.piper_voices_dir}")
        cfg = req.voice.get("piper") or {}
        wanted = _norm_voice_name(str(cfg.get("model") or ""))
        if wanted in files:
            return files[wanted], cfg.get("speaker")
        for k, p in files.items():  # partial match: "ryan-high" matches "en-us-ryan-high"
            if wanted and (wanted in k or k in wanted):
                return p, cfg.get("speaker")
        # deterministic fallback: pick a voice by character id so each character stays distinct
        keys = sorted(files)
        idx = sum(ord(c) for c in req.character_id) % len(keys)
        return files[keys[idx]], cfg.get("speaker")

    def cache_identity(self, req: VoiceRequest) -> dict:
        ident = super().cache_identity(req)
        model, speaker = self.resolve_model(req)
        ident["model"] = model.name
        ident["speaker"] = speaker
        return ident

    def synthesize(self, req: VoiceRequest, out_wav: Path) -> VoiceResult:
        model, speaker = self.resolve_model(req)
        length_scale = PIPER_PACE.get(req.pace, 1.0)
        if req.emotion in {"sad", "tired"}:
            length_scale *= 1.08
        elif req.emotion in {"excited", "angry", "scared", "shocked"}:
            length_scale *= 0.95
        noise = 0.667 + 0.12 * (req.intensity - 0.5)
        text = req.text.replace(" - ", ", ").replace("—", ", ")
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        if self.has_module:
            from piper import PiperVoice, SynthesisConfig

            voice = self._voices.get(str(model))
            if voice is None:
                voice = PiperVoice.load(str(model))
                self._voices[str(model)] = voice
            syn = SynthesisConfig(length_scale=length_scale, noise_scale=max(0.3, noise), noise_w_scale=0.8,
                                  speaker_id=speaker)
            with wave.open(str(out_wav), "wb") as wf:
                voice.synthesize_wav(text, wf, syn_config=syn)
        elif self.exe:
            args = [self.exe, "--model", str(model), "--output_file", str(out_wav),
                    "--length_scale", f"{length_scale:.3f}", "--noise_scale", f"{max(0.3, noise):.3f}"]
            if speaker is not None:
                args += ["--speaker", str(speaker)]
            run(args, input_text=text)
        else:
            raise TTSError("piper not available")
        if not out_wav.is_file() or out_wav.stat().st_size < 100:
            raise TTSError("piper produced no audio")
        return VoiceResult(out_wav, self.name, None, {"model": model.name, "speaker": speaker,
                                                      "length_scale": length_scale})


class EspeakTTS(TTSProvider):
    name = "espeak"

    def __init__(self, settings: Settings):
        self.exe = settings.tool("espeak")

    def available(self) -> bool:
        return bool(self.exe)

    def synthesize(self, req: VoiceRequest, out_wav: Path) -> VoiceResult:
        cfg = req.voice.get("espeak") or {}
        voice = cfg.get("voice", "en-us")
        pitch = int(cfg.get("pitch", 50))
        speed = int(cfg.get("speed", 165) * ESPEAK_PACE.get(req.pace, 1.0))
        amp = {"whisper": 60, "soft": 80, "normal": 110, "loud": 140, "shout": 170}.get(req.volume, 110)
        if req.emotion in {"excited", "shocked", "scared"}:
            pitch = min(99, pitch + int(10 * req.intensity))
        elif req.emotion in {"sad", "tired"}:
            pitch = max(0, pitch - int(8 * req.intensity))
            speed = int(speed * 0.92)
        if req.volume == "whisper":
            voice = voice.split("+")[0] + "+whisper"
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        run([self.exe, "-v", voice, "-p", str(pitch), "-s", str(speed), "-a", str(amp), "-g", "2",
             "-w", str(out_wav), req.text])
        return VoiceResult(out_wav, self.name, None, {"voice": voice, "pitch": pitch, "speed": speed})


class SilentTTS(TTSProvider):
    """No voice at all: lines get an estimated duration and are carried by captions."""

    name = "silent"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings

    def available(self) -> bool:
        return True

    def synthesize(self, req: VoiceRequest, out_wav: Path) -> VoiceResult:
        import numpy as np
        import soundfile as sf

        from storyforge.util.text import estimate_speech_seconds

        dur = estimate_speech_seconds(req.text, req.pace, req.emotion)
        sr = 48000
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_wav), np.zeros(int(dur * sr), dtype=np.float32), sr, subtype="PCM_16")
        return VoiceResult(out_wav, self.name, None, {"silent": True, "estimated_seconds": dur})
