"""Offline "writer" used in demo mode (no API keys).

For the bundled sample arc it returns the hand-written sample documents. For any other idea it
builds a structurally correct (hook -> setup -> escalation -> mini-payoff -> cliffhanger/payoff)
template screenplay from the arc plan, so the demo can always produce an MP4.
"""

from __future__ import annotations

import copy
import re

from storyforge.config import ASSETS_DIR
from storyforge.util.io import read_json
from storyforge.util.text import slugify, split_words

SAMPLES = ASSETS_DIR / "samples"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _short(text: str, max_words: int = 14) -> str:
    words = split_words(text)
    if len(words) <= max_words:
        return text.strip()
    cut = " ".join(words[:max_words]).rstrip(",;:")
    return cut + "..."


def sample_arc() -> dict:
    return read_json(SAMPLES / "arc.json")


def template_arc(idea: str, bible: dict, parts: int = 2) -> dict:
    chars = [c["id"] for c in bible.get("characters", [])][:3]
    locs = [loc["id"] for loc in bible.get("locations", [])] or ["library"]
    title = _short(idea, 6).rstrip(".!?") or "A New Mystery"
    plan = []
    for i in range(1, parts + 1):
        final = i == parts
        plan.append({
            "part": i,
            "title": f"{title} - Part {i}",
            "logline": _short(idea, 40),
            "hook": f"Something impossible happens: {_short(idea, 10)}",
            "escalation": "The friends dig deeper and the mystery gets bigger.",
            "mini_payoff": "One clue finally makes sense.",
            "cliffhanger": None if final else "A brand new clue changes everything.",
            "recap": None if i == 1 else "Previously: the mystery began.",
            "location": locs[(i - 1) % len(locs)],
            "time_of_day": "day" if i % 2 else "evening",
            "cast": chars,
            "music_mood": "mysterious" if not final else "triumphant",
        })
    return {"arc_id": slugify(title, 32), "title": title, "idea": idea[:1000],
            "premise": _short(idea, 60), "theme": "Friendship and curiosity",
            "final_payoff": "The friends solve the mystery together.", "parts": plan}


def sample_screenplay(arc_id: str, part: int) -> dict | None:
    if arc_id != sample_arc()["arc_id"]:
        return None
    p = SAMPLES / "screenplays" / f"part{part}.json"
    return read_json(p) if p.is_file() else None


def template_screenplay(arc: dict, part_plan: dict, bible: dict) -> dict:
    cast = part_plan.get("cast") or [c["id"] for c in bible.get("characters", [])][:3]
    chars = {c["id"]: c for c in bible.get("characters", [])}
    a = cast[0]
    b = cast[1] if len(cast) > 1 else cast[0]
    c = cast[2] if len(cast) > 2 else b
    final = part_plan.get("cliffhanger") is None

    def catch(cid, default):
        cps = chars.get(cid, {}).get("catchphrases") or []
        return cps[0] if cps else default

    beats = []

    def add(speaker, line, emotion, intensity, action, note, beat_type, gesture=None, camera=None, addressee=None,
            fx=None, sfx=None):
        beats.append({
            "id": f"b{len(beats) + 1:02d}", "speaker": speaker, "addressee": addressee if speaker else None,
            "line": line if speaker else "", "emotion": emotion, "intensity": intensity, "action": action,
            "performance_note": note, "camera_hint": camera, "beat_type": beat_type, "gesture": gesture,
            "motion": None, "props": [], "fx": fx or [], "sfx": sfx or [],
            "delivery": {"pace": "normal", "volume": "normal"} if speaker else {}})

    hook = _short(part_plan.get("hook", "Wait. Did you see that?"), 12)
    add(a, hook if hook.endswith(("!", "?")) else hook.rstrip(".") + "!", "shocked", 0.9,
        "Everyone freezes as something strange happens.", "urgent", "hook", "point", "snap_zoom", b)
    add(b, "Okay. Nobody panic. Tell me exactly what you saw.", "neutral", 0.45, "Steps closer, calm.",
        "steady", "setup", None, "medium", a)
    add(c, "I'm not panicking. You're panicking.", "scared", 0.55, "Hides behind the others.", "nervous joke",
        "joke", "shiver", "close_up", b)
    for s in _sentences(part_plan.get("logline", ""))[:2]:
        add(a, _short(s, 14), "excited", 0.65, "Explains with big gestures.", "fast", "setup", "talk", "two_shot", b)
    add(b, _short(part_plan.get("escalation", "This is bigger than we thought."), 14), "determined", 0.7,
        "Leans in to look closer.", "focused", "escalation", "lean_in", "push_in", a)
    add(None, "", "shocked", 0.8, "A clue is revealed.", "everyone gasps", "reveal", "gasp", "insert",
        sfx=["reveal_sting"])
    add(c, catch(c, "Whoa."), "embarrassed", 0.6, "Grins sheepishly.", "comic", "joke", "shrug", "close_up", a,
        fx=[{"character": c, "type": "sweat_drop"}])
    add(b, _short(part_plan.get("mini_payoff", "Now it makes sense."), 14), "smug", 0.65,
        "Folds arms, pleased.", "satisfied", "payoff", "cross_arms", "close_up", a,
        fx=[{"character": b, "type": "lightbulb"}])
    add(a, catch(a, "Let's go!"), "happy", 0.7, "Pumps a fist.", "excited", "joke", "cheer", "medium", b)
    if final:
        add(None, "", "happy", 1.0, "Everything falls into place.", "joy", "payoff", "cheer", "crane_up",
            sfx=["reveal_sting"])
        add(b, "Case closed.", "happy", 0.6, "Smiles at the others.", "warm", "resolution", "thumbs_up", "two_shot", a)
    else:
        add(None, "", "shocked", 1.0, _short(part_plan.get("cliffhanger") or "Something changes.", 20),
            "sudden", "cliffhanger", "gasp", "whip_pan", sfx=["reveal_sting"])
        add(c, "That... was not supposed to happen. Right?", "scared", 0.9, "Turns slowly to the others.",
            "tiny voice", "cliffhanger", None, "push_in", a)
    return {"schema_version": 1, "title": part_plan.get("title", arc.get("title", "Untitled"))[:80],
            "logline": part_plan.get("logline", "")[:300], "part": part_plan.get("part", 1), "cast": cast,
            "location": part_plan.get("location") or bible["locations"][0]["id"],
            "time_of_day": part_plan.get("time_of_day", "day"), "music_mood": part_plan.get("music_mood", "playful"),
            "hook": hook[:200], "mini_payoff": (part_plan.get("mini_payoff") or "")[:240],
            "cliffhanger": part_plan.get("cliffhanger"), "beats": beats}


def template_continuity(sp: dict) -> dict:
    spoken = [b for b in sp.get("beats", []) if b.get("line")]
    key = [b for b in sp.get("beats", []) if b.get("beat_type") in ("reveal", "payoff", "cliffhanger")]
    summary = f"In '{sp.get('title')}', " + "; ".join(_short(b.get("action", ""), 16).rstrip(".") for b in key[:4])
    facts = [_short(b["action"], 30) for b in key[:5] if b.get("action")]
    objects = sorted({f"{p['character']} {p['action'].replace('_', ' ')}s the {p['prop']}"
                      for b in sp.get("beats", []) for p in b.get("props", [])})[:6]
    return {"summary": (summary + ".")[:700],
            "changes": {"relationships": [], "objects": objects, "secrets": [], "facts": facts},
            "open_threads": [sp["cliffhanger"]] if sp.get("cliffhanger") else [],
            "_lines": len(spoken)}


def template_metadata(sp: dict, bible: dict) -> dict:
    series = bible.get("title", "Series")
    part = sp.get("part", 1)
    tag_series = "#" + re.sub(r"[^A-Za-z0-9]", "", series)[:40]
    title = sp.get("title", "Untitled")
    hook = sp.get("hook") or (sp.get("beats") or [{}])[0].get("line", "")
    return {
        "titles": [f"{title} | {series} Part {part}", f"{hook[:60]}", f"{series}: {title}"],
        "description": f"{sp.get('logline', '')} Part {part} of an original animated mini-series. "
                       f"Follow for the next part!"[:600],
        "hashtags": [tag_series[:41] if len(tag_series) > 3 else "#AnimatedShort", "#AnimatedShort", "#Animation",
                     "#Mystery", "#KidsCartoon", "#StoryTime", "#Shorts"],
    }


def demo_generate(task: str, context: dict) -> dict:
    if task == "arc_plan":
        idea = context.get("idea", "")
        arc = sample_arc()
        if not idea.strip() or idea.strip().lower() in arc["idea"].lower() or "clock" in idea.lower():
            out = copy.deepcopy(arc)
            if context.get("parts") and context["parts"] != len(out["parts"]):
                return template_arc(idea or arc["idea"], context["bible"], context["parts"])
            return out
        return template_arc(idea, context["bible"], context.get("parts") or 2)
    if task == "screenplay":
        arc, plan = context["arc"], context["part_plan"]
        sp = sample_screenplay(arc.get("arc_id", ""), plan["part"])
        return copy.deepcopy(sp) if sp else template_screenplay(arc, plan, context["bible"])
    if task == "script_review":
        findings = context.get("findings") or {"scores": {}, "notes": [], "rewrites": []}
        return {"scores": findings["scores"], "notes": findings["notes"], "rewrites": []}
    if task == "continuity_log":
        doc = template_continuity(context["screenplay"])
        doc.pop("_lines", None)
        return doc
    if task == "continuity_check":
        return {"issues": context.get("rule_issues", [])}
    if task == "metadata":
        return template_metadata(context["screenplay"], context["bible"])
    raise KeyError(task)
