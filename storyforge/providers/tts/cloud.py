"""Cloud TTS providers: ElevenLabs (best quality, character timestamps) and OpenAI TTS
(per-line natural-language `instructions` for voice direction)."""

from __future__ import annotations

import base64
import re
import time
from pathlib import Path

import httpx

from storyforge.config import Settings
from storyforge.providers.tts.base import (
    TTSError,
    TTSProvider,
    VoiceRequest,
    VoiceResult,
    emotion_direction_text,
)
from storyforge.util.ffmpeg import ffmpeg
from storyforge.util.io import read_json, write_json

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def _post_with_retry(client: httpx.Client, url: str, attempts: int = 4, **kw) -> httpx.Response:
    delay = 1.5
    last: Exception | None = None
    for i in range(attempts):
        try:
            r = client.post(url, **kw)
            if r.status_code in RETRY_STATUS and i < attempts - 1:
                time.sleep(float(r.headers.get("retry-after", delay)))
                delay *= 2
                continue
            return r
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last = exc
            time.sleep(delay)
            delay *= 2
    raise TTSError(f"request failed after {attempts} attempts: {last}")


# --------------------------------------------------------------------------- ElevenLabs
V3_TAGS = {
    "whisper": "[whispers]", "shout": "[shouting]", "soft": "[softly]",
    "happy": "[cheerfully]", "excited": "[excited]", "sad": "[sad]", "angry": "[angry]",
    "scared": "[nervous]", "shocked": "[gasps]", "smug": "[smugly]", "confused": "[confused]",
    "embarrassed": "[sheepishly]", "tired": "[tired]", "determined": "[determined]",
}


def chars_to_words(chars: list[str], starts: list[float], ends: list[float]) -> list[dict]:
    """ElevenLabs character alignment -> word timings (audio tags in [] are skipped)."""
    words, cur, s0, e0, in_tag = [], "", None, None, False
    for ch, s, e in zip(chars, starts, ends, strict=False):
        if ch == "[":
            in_tag = True
            continue
        if in_tag:
            if ch == "]":
                in_tag = False
            continue
        if ch.isspace():
            if cur:
                words.append({"word": cur, "start": s0, "end": e0})
            cur, s0, e0 = "", None, None
            continue
        if not cur:
            s0 = s
        cur += ch
        e0 = e
    if cur:
        words.append({"word": cur, "start": s0, "end": e0})
    return [w for w in words if re.search(r"\w", w["word"])]


class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"
    natural_voice = True
    base = "https://api.elevenlabs.io/v1"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.key = settings.elevenlabs_api_key
        self.model = settings.elevenlabs_model
        self._voices: list[dict] | None = None

    def available(self) -> bool:
        return bool(self.key)

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=120, headers={"xi-api-key": self.key})

    def _list_voices(self) -> list[dict]:
        if self._voices is None:
            with self._client() as c:
                r = c.get(f"{self.base}/voices")
                if r.status_code != 200:
                    raise TTSError(f"ElevenLabs /voices failed: {r.status_code} {r.text[:200]}")
                self._voices = r.json().get("voices", [])
        return self._voices

    def voice_id(self, req: VoiceRequest) -> str:
        cfg = req.voice.get("elevenlabs") or {}
        if cfg.get("voice_id"):
            return cfg["voice_id"]
        # Deterministic auto-pick by labels, remembered so the character keeps its voice forever.
        memo_path = self.settings.data_dir / "cache" / "elevenlabs_voice_choices.json"
        memo = read_json(memo_path, {})
        if req.character_id in memo:
            return memo[req.character_id]
        want = cfg.get("labels") or {}
        taken = set(memo.values())
        best, best_score = None, -1e9
        for v in self._list_voices():
            labels = {k: str(val).lower() for k, val in (v.get("labels") or {}).items()}
            score = sum(2 for k, val in want.items() if labels.get(k, "").startswith(str(val).lower()[:4]))
            score -= 3 if v["voice_id"] in taken else 0
            score += (sum(map(ord, req.character_id + v["voice_id"])) % 7) * 0.01  # stable tie-break
            if score > best_score:
                best, best_score = v["voice_id"], score
        if not best:
            raise TTSError("no ElevenLabs voices available on this account")
        memo[req.character_id] = best
        write_json(memo_path, memo)
        return best

    def voice_settings(self, req: VoiceRequest) -> dict:
        expressive = req.intensity if req.emotion != "neutral" else 0.2
        return {
            "stability": round(max(0.25, 0.62 - 0.35 * expressive), 2),
            "similarity_boost": 0.78,
            "style": round(min(0.7, 0.1 + 0.55 * expressive), 2),
            "use_speaker_boost": True,
            "speed": {"slow": 0.9, "normal": 1.0, "fast": 1.1}.get(req.pace, 1.0),
        }

    def _text(self, req: VoiceRequest) -> str:
        text = req.text
        if self.model.startswith("eleven_v3"):
            tags = []
            if req.volume in V3_TAGS:
                tags.append(V3_TAGS[req.volume])
            if req.emotion in V3_TAGS and req.intensity >= 0.35:
                tags.append(V3_TAGS[req.emotion])
            text = " ".join(tags + [text])
        return text

    def cache_identity(self, req: VoiceRequest) -> dict:
        ident = super().cache_identity(req)
        ident.update({"model": self.model, "voice_id": self.voice_id(req), "settings": self.voice_settings(req)})
        return ident

    def synthesize(self, req: VoiceRequest, out_wav: Path) -> VoiceResult:
        vid = self.voice_id(req)
        body = {"text": self._text(req), "model_id": self.model, "voice_settings": self.voice_settings(req)}
        if req.previous_text and not self.model.startswith("eleven_v3"):
            body["previous_text"] = req.previous_text[-400:]
        if req.next_text and not self.model.startswith("eleven_v3"):
            body["next_text"] = req.next_text[:400]
        mp3 = out_wav.with_suffix(".mp3")
        words = None
        with self._client() as c:
            r = _post_with_retry(c, f"{self.base}/text-to-speech/{vid}/with-timestamps",
                                 params={"output_format": "mp3_44100_128"}, json=body)
            if r.status_code == 200:
                data = r.json()
                mp3.write_bytes(base64.b64decode(data["audio_base64"]))
                al = data.get("alignment") or data.get("normalized_alignment")
                if al:
                    words = chars_to_words(al["characters"], al["character_start_times_seconds"],
                                           al["character_end_times_seconds"])
            else:
                # Some models (e.g. eleven_v3) may not support timestamps: plain endpoint + alignment later.
                r2 = _post_with_retry(c, f"{self.base}/text-to-speech/{vid}",
                                      params={"output_format": "mp3_44100_128"}, json=body)
                if r2.status_code != 200:
                    raise TTSError(f"ElevenLabs TTS failed: {r2.status_code} {r2.text[:300]}")
                mp3.write_bytes(r2.content)
        ffmpeg(["-i", str(mp3), "-ac", "1", "-ar", "48000", str(out_wav)])
        mp3.unlink(missing_ok=True)
        return VoiceResult(out_wav, self.name, words, {"voice_id": vid, "model": self.model})


# --------------------------------------------------------------------------- OpenAI TTS
class OpenAITTS(TTSProvider):
    name = "openai"
    natural_voice = True

    def __init__(self, settings: Settings):
        self.settings = settings
        self.key = settings.openai_api_key
        self.model = settings.openai_tts_model
        self.base = settings.openai_base_url

    def available(self) -> bool:
        return bool(self.key)

    def voice(self, req: VoiceRequest) -> str:
        cfg = req.voice.get("openai") or {}
        return cfg.get("voice") or ["verse", "coral", "ash", "sage", "ballad", "nova"][
            sum(map(ord, req.character_id)) % 6]

    def instructions(self, req: VoiceRequest) -> str:
        return ("Voice acting for an animated kids' short. " + emotion_direction_text(req)).strip()

    def cache_identity(self, req: VoiceRequest) -> dict:
        ident = super().cache_identity(req)
        ident.update({"model": self.model, "voice_name": self.voice(req), "instructions": self.instructions(req)})
        return ident

    def synthesize(self, req: VoiceRequest, out_wav: Path) -> VoiceResult:
        body = {"model": self.model, "voice": self.voice(req), "input": req.text, "response_format": "wav"}
        if "tts-1" in self.model:
            body["speed"] = {"slow": 0.9, "normal": 1.0, "fast": 1.12}.get(req.pace, 1.0)
        else:
            body["instructions"] = self.instructions(req)
        raw = out_wav.with_suffix(".src.wav")
        with httpx.Client(timeout=120, headers={"Authorization": f"Bearer {self.key}"}) as c:
            r = _post_with_retry(c, f"{self.base}/audio/speech", json=body)
            if r.status_code != 200:
                raise TTSError(f"OpenAI TTS failed: {r.status_code} {r.text[:300]}")
            raw.write_bytes(r.content)
        ffmpeg(["-i", str(raw), "-ac", "1", "-ar", "48000", str(out_wav)])
        raw.unlink(missing_ok=True)
        return VoiceResult(out_wav, self.name, None, {"voice": body["voice"], "model": self.model})
