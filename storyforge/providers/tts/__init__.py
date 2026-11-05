"""TTS provider selection.

``auto`` order: ElevenLabs -> OpenAI TTS -> Piper -> espeak-ng -> silent. One provider is
chosen per run (not per line) so every character keeps one consistent voice.
"""

from __future__ import annotations

from storyforge.config import Settings
from storyforge.providers.tts.base import TTSError, TTSProvider, VoiceRequest, VoiceResult
from storyforge.providers.tts.cloud import ElevenLabsTTS, OpenAITTS
from storyforge.providers.tts.offline import EspeakTTS, PiperTTS, SilentTTS

ORDER = ["elevenlabs", "openai", "piper", "espeak", "silent"]
CLASSES = {"elevenlabs": ElevenLabsTTS, "openai": OpenAITTS, "piper": PiperTTS, "espeak": EspeakTTS,
           "silent": SilentTTS}

__all__ = ["TTSProvider", "VoiceRequest", "VoiceResult", "TTSError", "get_tts_chain", "available_providers"]


def available_providers(settings: Settings) -> dict[str, bool]:
    out = {}
    for name in ORDER:
        try:
            out[name] = CLASSES[name](settings).available()
        except Exception:
            out[name] = False
    return out


def get_tts_chain(settings: Settings) -> list[TTSProvider]:
    """Providers in preference order, the configured/primary one first. Always ends with silent."""
    pref = settings.tts_provider
    if settings.demo_forced and pref == "auto":
        names = ["piper", "espeak", "silent"]
    elif pref in CLASSES:
        names = [pref] + [n for n in ORDER if n != pref]
    else:
        names = ORDER
    chain = []
    for n in names:
        try:
            p = CLASSES[n](settings)
        except Exception:
            continue
        if p.available():
            chain.append(p)
    if not any(p.name == "silent" for p in chain):
        chain.append(SilentTTS())
    return chain
