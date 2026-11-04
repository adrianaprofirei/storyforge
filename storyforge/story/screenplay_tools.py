"""Screenplay semantics: cross-reference validation, review application and user edits."""

from __future__ import annotations

import copy
import re

from storyforge.models.constants import BASE_EXPRESSIONS
from storyforge.util.text import estimate_speech_seconds

REAL_BRANDS = {
    # A small denylist for the "no real brands" content rule; the LLM continuity check covers the rest.
    "coca-cola", "coke", "pepsi", "nike", "adidas", "apple watch", "iphone", "ipad", "android", "samsung",
    "mcdonald", "starbucks", "lego", "roblox", "minecraft", "fortnite", "disney", "pokemon", "nintendo",
    "playstation", "xbox", "youtube", "tiktok", "instagram", "google", "amazon", "netflix", "marvel",
}
VIOLENT_WORDS = {"kill", "blood", "gun", "knife", "stab", "shoot", "murder", "dead body", "weapon"}


def semantic_errors(sp: dict, bible: dict | None = None, cast_ids: set[str] | None = None,
                    location_ids: set[str] | None = None, part_seconds: tuple[float, float] | None = None) -> list[str]:
    errors: list[str] = []
    cast = set(sp.get("cast", []))
    if cast_ids is not None:
        unknown = cast - cast_ids
        if unknown:
            errors.append(f"cast: unknown characters {sorted(unknown)} (known: {sorted(cast_ids)})")
    if location_ids is not None and sp.get("location") not in location_ids:
        errors.append(f"location: '{sp.get('location')}' is not a bible location ({sorted(location_ids)})")
    seen = set()
    total = 0.0
    speaking_beats = 0
    for i, b in enumerate(sp.get("beats", [])):
        bid = b.get("id", f"#{i}")
        if bid in seen:
            errors.append(f"beats/{i}: duplicate beat id {bid}")
        seen.add(bid)
        spk = b.get("speaker")
        line = (b.get("line") or "").strip()
        if spk is not None and spk not in cast:
            errors.append(f"beats/{i} ({bid}): speaker '{spk}' is not in cast")
        if spk and not line:
            errors.append(f"beats/{i} ({bid}): speaker set but line is empty")
        if not spk and line:
            errors.append(f"beats/{i} ({bid}): line without speaker (use speaker=null only for silent beats)")
        add = b.get("addressee")
        if add is not None and add not in cast:
            errors.append(f"beats/{i} ({bid}): addressee '{add}' is not in cast")
        if add is not None and add == spk:
            errors.append(f"beats/{i} ({bid}): addressee equals speaker")
        for p in b.get("props", []) or []:
            if p.get("character") not in cast:
                errors.append(f"beats/{i} ({bid}): prop holder '{p.get('character')}' is not in cast")
        for fx in b.get("fx", []) or []:
            if fx.get("character") not in cast:
                errors.append(f"beats/{i} ({bid}): fx character '{fx.get('character')}' is not in cast")
        mo = b.get("motion")
        if mo and mo.get("character") and mo["character"] not in cast:
            errors.append(f"beats/{i} ({bid}): motion character '{mo['character']}' is not in cast")
        text = f"{line} {b.get('action', '')}".lower()
        for brand in REAL_BRANDS:
            if re.search(rf"\b{re.escape(brand)}\b", text):
                errors.append(f"beats/{i} ({bid}): mentions real brand '{brand}' (content rule: no real brands)")
        if bible and any("violence" in r.lower() for r in bible.get("world", {}).get("content_rules", [])):
            for w in VIOLENT_WORDS:
                if re.search(rf"\b{re.escape(w)}\b", text):
                    errors.append(f"beats/{i} ({bid}): '{w}' conflicts with the no-violence content rule")
        if line:
            speaking_beats += 1
            total += estimate_speech_seconds(line, (b.get("delivery") or {}).get("pace", "normal"), b.get("emotion"))
        total += 0.3 if line else 1.6
    if speaking_beats < 2:
        errors.append("beats: a part needs at least two spoken lines")
    if part_seconds:
        lo, hi = part_seconds
        if total < lo * 0.75:
            errors.append(f"beats: estimated runtime {total:.0f}s is too short (target {lo:.0f}-{hi:.0f}s); add beats")
        if total > hi * 1.1:
            errors.append(f"beats: estimated runtime {total:.0f}s is too long (target {lo:.0f}-{hi:.0f}s); cut beats")
    return errors


def estimated_runtime(sp: dict) -> float:
    total = 0.0
    for b in sp.get("beats", []):
        line = (b.get("line") or "").strip()
        if line:
            total += estimate_speech_seconds(line, (b.get("delivery") or {}).get("pace", "normal"), b.get("emotion")) + 0.3
        else:
            total += 1.6
    return total


def normalize(sp: dict) -> dict:
    """Fill optional fields with defaults so downstream code can rely on them."""
    sp = copy.deepcopy(sp)
    for b in sp.get("beats", []):
        b.setdefault("addressee", None)
        b.setdefault("camera_hint", None)
        b.setdefault("beat_type", "setup")
        b.setdefault("gesture", None)
        b.setdefault("motion", None)
        b.setdefault("props", [])
        b.setdefault("fx", [])
        b.setdefault("sfx", [])
        d = b.setdefault("delivery", {})
        d.setdefault("pace", "normal")
        d.setdefault("volume", "normal")
        b["line"] = (b.get("line") or "").strip()
        if b.get("emotion") not in BASE_EXPRESSIONS and b.get("emotion") is None:
            b["emotion"] = "neutral"
        if not b.get("addressee") and b.get("speaker"):
            others = [c for c in sp.get("cast", []) if c != b["speaker"]]
            b["addressee"] = others[0] if others else None
    return sp


def apply_review(sp: dict, review: dict) -> dict:
    out = copy.deepcopy(sp)
    beats = out["beats"]
    by_id = {b["id"]: i for i, b in enumerate(beats)}
    for rw in review.get("rewrites", []) or []:
        if rw.get("id") in by_id:
            beats[by_id[rw["id"]]] = rw
    for ins in review.get("insert_after", []) or []:
        after, beat = ins.get("after"), ins.get("beat")
        ids = [b["id"] for b in beats]
        if after in ids and beat and beat.get("id") not in ids:
            beats.insert(ids.index(after) + 1, beat)
    remove = set(review.get("remove", []) or [])
    if remove and len(beats) - len(remove) >= 3:
        out["beats"] = [b for b in beats if b["id"] not in remove]
    return out


EDITABLE_FIELDS = {"speaker", "addressee", "line", "emotion", "intensity", "action", "performance_note",
                   "camera_hint", "beat_type", "gesture", "motion", "props", "fx", "sfx", "delivery"}


def apply_edits(sp: dict, edits: dict) -> dict:
    """User edits from the beat editor: {"beats": {beat_id: {field: value}}, "order": [...], "deleted": [...],
    "added": [beat, ...]} — applied last so they survive re-reviews."""
    if not edits:
        return sp
    out = copy.deepcopy(sp)
    beats = {b["id"]: b for b in out["beats"]}
    for bid, fields in (edits.get("beats") or {}).items():
        if bid in beats:
            for k, v in fields.items():
                if k in EDITABLE_FIELDS:
                    beats[bid][k] = v
    for beat in edits.get("added") or []:
        if beat.get("id") and beat["id"] not in beats:
            beats[beat["id"]] = beat
            out["beats"].append(beat)
    deleted = set(edits.get("deleted") or [])
    order = edits.get("order")
    seq = [beats[i] for i in order if i in beats] if order else out["beats"]
    seq += [b for b in out["beats"] if b not in seq]
    out["beats"] = [b for b in seq if b["id"] not in deleted]
    for k in ("title", "logline", "location", "time_of_day", "music_mood", "cast"):
        if k in edits:
            out[k] = edits[k]
    return out


def next_beat_id(sp: dict) -> str:
    nums = [int(b["id"][1:]) for b in sp.get("beats", []) if re.fullmatch(r"b\d+", b.get("id", ""))]
    return f"b{(max(nums) + 1 if nums else 1):02d}"
