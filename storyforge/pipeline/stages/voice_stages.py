"""voices + lipsync stages (fine-grained per-line caching)."""

from __future__ import annotations

import shutil
from pathlib import Path

from storyforge.audio.voice import prepare_line
from storyforge.performance.lipsync import estimate_cues, rhubarb_version, run_rhubarb
from storyforge.pipeline.cache import ItemCache
from storyforge.pipeline.runner import Stage
from storyforge.providers.align import align_words
from storyforge.providers.tts import TTSError, VoiceRequest
from storyforge.util.hashing import file_hash, maybe_file_hash, stable_hash
from storyforge.util.io import read_json, write_json

VOICE_POST_VERSION = "3"


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        dst.hardlink_to(src)
    except OSError:
        shutil.copy2(src, dst)


def voice_requests(sp: dict, cast: dict, bible: dict) -> list[tuple[dict, VoiceRequest]]:
    chars = {c["id"]: c for c in bible.get("characters", [])}
    spoken = [b for b in sp["beats"] if b.get("speaker") and b.get("line")]
    out = []
    for i, b in enumerate(spoken):
        cid = b["speaker"]
        voice = (cast.get(cid) or {}).get("voice", {})
        base = voice.get("base_direction") or chars.get(cid, {}).get("voice_direction", "")
        direction = "; ".join(x for x in [base, b.get("performance_note", "")] if x)
        d = b.get("delivery") or {}
        out.append((b, VoiceRequest(
            text=b["line"], character_id=cid, voice=voice, emotion=b.get("emotion", "neutral"),
            intensity=float(b.get("intensity", 0.5)), pace=d.get("pace", "normal"), volume=d.get("volume", "normal"),
            direction=direction,
            previous_text=spoken[i - 1]["line"] if i > 0 else "",
            next_text=spoken[i + 1]["line"] if i + 1 < len(spoken) else "")))
    return out


class VoicesStage(Stage):
    code = ("providers/*.py", "providers/tts/*.py", "audio/voice.py")
    name = "voices"
    version = "2"
    weight = 4.0

    def inputs(self, ctx):
        sp = read_json(ctx.path("screenplay.final.json"))
        lines = [{"id": b["id"], "speaker": b.get("speaker"), "line": b.get("line"), "emotion": b.get("emotion"),
                  "intensity": b.get("intensity"), "note": b.get("performance_note"), "delivery": b.get("delivery")}
                 for b in sp["beats"] if b.get("line")]
        cast = ctx.cast()
        voices = {cid: cast.get(cid, {}).get("voice") for cid in sp.get("cast", [])}
        return {"lines": lines, "voices": voices, "chain": [p.name for p in ctx.tts],
                "alignment": ctx.settings.alignment_mode, "post": VOICE_POST_VERSION}

    def outputs(self, ctx):
        return [ctx.path("voices", "manifest.json")]

    def run(self, ctx):
        sp = read_json(ctx.path("screenplay.final.json"))
        cast, bible = ctx.cast(), ctx.bible()
        reqs = voice_requests(sp, cast, bible)
        cache = ItemCache(ctx.global_cache("tts"))
        chain = ctx.tts
        primary = chain[0]
        ctx.log(f"voices via {primary.name} (chain: {', '.join(p.name for p in chain)})")
        vdir = ctx.sub("voices")
        manifest = {"provider": primary.name, "silent": primary.name == "silent", "lines": {}}
        for n, (beat, req) in enumerate(reqs):
            ctx.check_cancel()
            ctx.progress(n / max(1, len(reqs)), f"line {beat['id']}")
            used = None
            for prov in chain:
                try:
                    ident = prov.cache_identity(req)
                except Exception as exc:
                    ctx.log(f"{prov.name} unavailable for {beat['id']}: {exc}")
                    continue
                pitch = 0.0 if prov.natural_voice else float(req.voice.get("pitch_semitones", 0.0))
                key = stable_hash("tts", ident, pitch, VOICE_POST_VERSION)
                wav = cache.get(key, ".wav")
                meta = cache.meta(key)
                if wav is None or meta is None:
                    raw = cache.path(key, ".raw.wav")
                    try:
                        res = prov.synthesize(req, raw)
                    except (TTSError, Exception) as exc:  # fall through to the next provider
                        ctx.log(f"{prov.name} failed on {beat['id']}: {exc}")
                        continue
                    wav = cache.path(key, ".wav")
                    info = prepare_line(raw, wav, pitch, req.volume, apply_volume_style=not prov.natural_voice)
                    raw.unlink(missing_ok=True)
                    words, source = align_words(ctx.settings, req.text, wav, res.words, silent=prov.name == "silent")
                    meta = {"provider": prov.name, "duration": info["duration"], "words": words,
                            "alignment": source, "provider_meta": res.meta, "text": req.text}
                    cache.put_meta(key, meta)
                used = (prov, wav, meta)
                break
            if used is None:
                raise TTSError(f"no TTS provider could voice beat {beat['id']}")
            prov, wav, meta = used
            dst = vdir / f"{beat['id']}.wav"
            _copy(wav, dst)
            if prov.name != primary.name:
                ctx.log(f"WARNING: {beat['id']} voiced by fallback provider {prov.name}")
            manifest["lines"][beat["id"]] = {
                "file": f"voices/{beat['id']}.wav", "speaker": beat["speaker"], "duration": meta["duration"],
                "words": meta["words"], "provider": prov.name, "alignment": meta["alignment"],
                "silent": prov.name == "silent", "hash": file_hash(dst)}
        write_json(ctx.path("voices", "manifest.json"), manifest)
        return {"provider": primary.name, "lines": len(manifest["lines"])}


class LipSyncStage(Stage):
    code = ("performance/lipsync.py",)
    name = "lipsync"
    version = "2"
    weight = 2.0

    def inputs(self, ctx):
        exe = ctx.settings.tool("rhubarb")
        return {"voices": maybe_file_hash(ctx.path("voices", "manifest.json")), "rhubarb": bool(exe)}

    def outputs(self, ctx):
        return [ctx.path("lipsync", "manifest.json")]

    def run(self, ctx):
        vm = read_json(ctx.path("voices", "manifest.json"))
        exe = ctx.settings.tool("rhubarb")
        version = rhubarb_version(exe) if exe else None
        cache = ItemCache(ctx.global_cache("lipsync"))
        out = {"tool": f"rhubarb {version}" if exe else "estimator", "lines": {}}
        items = list(vm["lines"].items())
        for n, (bid, line) in enumerate(items):
            ctx.check_cancel()
            ctx.progress(n / max(1, len(items)), bid)
            wav = ctx.path(line["file"])
            text = " ".join(w["word"] for w in line["words"])
            if line.get("silent") or not exe:
                cues = estimate_cues(line["words"], None if line.get("silent") else wav, line["duration"])
                out["lines"][bid] = {"cues": cues, "source": "estimator"}
                continue
            key = stable_hash("rhubarb", line["hash"], text, version)
            hit = cache.meta(key)
            if hit is None:
                try:
                    cues = run_rhubarb(exe, wav, text, cache.path(key, ".rhubarb.json"))
                    hit = {"cues": cues, "source": "rhubarb"}
                except Exception as exc:
                    ctx.log(f"rhubarb failed on {bid} ({exc}); using estimator")
                    hit = {"cues": estimate_cues(line["words"], wav, line["duration"]), "source": "estimator"}
                cache.put_meta(key, hit)
            out["lines"][bid] = hit
        write_json(ctx.path("lipsync", "manifest.json"), out)
        return {"tool": out["tool"], "lines": len(out["lines"])}
