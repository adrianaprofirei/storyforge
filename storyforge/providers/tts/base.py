"""TTS provider interface.

A provider turns one screenplay line + voice direction into a WAV file and, when it can,
word-level timings. Providers never post-process audio (pitch, trimming, loudness, EQ):
that is done uniformly by :mod:`storyforge.audio.voice` so every provider sounds consistent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class VoiceRequest:
    text: str
    character_id: str
    voice: dict                       # cast registry `voice` block
    emotion: str = "neutral"
    intensity: float = 0.5
    pace: str = "normal"              # slow | normal | fast
    volume: str = "normal"            # whisper | soft | normal | loud | shout
    direction: str = ""               # performance note + character base direction
    previous_text: str = ""           # context for providers that use it (ElevenLabs)
    next_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VoiceResult:
    wav_path: Path
    provider: str
    words: list[dict] | None = None   # [{"word": str, "start": s, "end": s}] relative to file start
    meta: dict = field(default_factory=dict)


class TTSError(RuntimeError):
    pass


class TTSProvider:
    name = "base"
    #: providers that sound like a specific person should not be pitch-shifted
    natural_voice = False

    def available(self) -> bool:
        return False

    def cache_identity(self, req: VoiceRequest) -> dict:
        """Everything that changes the produced audio (used for the line cache key)."""
        return {"provider": self.name, "voice": req.voice.get(self.name), "text": req.text,
                "emotion": req.emotion, "intensity": round(req.intensity, 2), "pace": req.pace,
                "volume": req.volume, "direction": req.direction}

    def synthesize(self, req: VoiceRequest, out_wav: Path) -> VoiceResult:
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


def emotion_direction_text(req: VoiceRequest) -> str:
    """Natural-language voice direction (OpenAI `instructions`, logs, UI)."""
    parts = []
    if req.direction:
        parts.append(req.direction)
    strength = "slightly" if req.intensity < 0.35 else ("very" if req.intensity > 0.75 else "")
    if req.emotion and req.emotion != "neutral":
        parts.append(f"Emotion: {strength} {req.emotion}".replace("  ", " "))
    if req.volume in {"whisper", "shout", "soft", "loud"}:
        parts.append({"whisper": "Whisper the line.", "shout": "Shout the line.",
                      "soft": "Speak softly.", "loud": "Speak loudly and projected."}[req.volume])
    if req.pace in {"slow", "fast"}:
        parts.append("Pace: slow, deliberate." if req.pace == "slow" else "Pace: fast, energetic.")
    return " ".join(parts)
