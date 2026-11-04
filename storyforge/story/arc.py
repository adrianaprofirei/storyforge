"""Arc planner: a story idea -> a 2-5 part arc plan, tracked in the series bible.

Each part gets a hook (first 1-2 s), an escalation, a mini-payoff and - except the finale - a
cliffhanger; parts 2+ get a one-line recap for their 2-3 s "previously" opening. The plan is
validated against ``arc.schema.json`` plus semantic rules (part numbering, cast and location ids
from the bible, cliffhanger/recap placement) and saved to ``arcs/<arc_id>.json``; the arc and its
episodes are registered in the bible, and one episode folder per part is created.
"""

from __future__ import annotations

import json
import re

from storyforge.models.constants import MUSIC_MOODS, TIMES_OF_DAY

ARC_SYSTEM = f"""You are the showrunner of an original animated series of vertical (9:16) shorts.
Plan a multi-part story arc from the user's idea as JSON matching the provided schema.

Rules:
- Exactly the requested number of parts (2-5). Each part plays in 45-90 seconds.
- Every part has its own HOOK (what grabs the viewer in the first 1-2 seconds: a striking image or
  a short line), a clear ESCALATION, a satisfying MINI-PAYOFF and - for every part except the
  last - a CLIFFHANGER that makes viewers need the next part. The final part has cliffhanger null
  and lands the arc's final_payoff.
- Parts 2+ open with a 2-3 second visual recap: give each a one-sentence `recap` (max 120
  characters) of what the viewer must remember. Part 1's recap is null.
- Use ONLY character ids and location ids from the bible (2-4 characters per part), keep everyone
  in character, respect every content rule, and stay consistent with the continuity log (never
  contradict earlier episodes; paying off an open thread is great).
- time_of_day is one of {", ".join(TIMES_OF_DAY)}; music_mood one of {", ".join(MUSIC_MOODS)}.
- Titles are short (max 60 characters) and in the series tone; loglines are one or two sentences.
Reply with the JSON document only."""


def arc_semantic_errors(arc: dict, parts: int, cast_ids: set[str], loc_ids: set[str]) -> list[str]:
    errors: list[str] = []
    plan = arc.get("parts", [])
    if len(plan) != parts:
        errors.append(f"the arc must have exactly {parts} parts (got {len(plan)})")
    for i, p in enumerate(plan, start=1):
        tag = f"part {p.get('part', i)}"
        if p.get("part") != i:
            errors.append(f"parts must be numbered 1..{len(plan)} in order; entry {i} has part={p.get('part')}")
        final = i == len(plan)
        if final and p.get("cliffhanger"):
            errors.append(f"{tag} is the finale: cliffhanger must be null (land the final payoff instead)")
        if not final and not (p.get("cliffhanger") or "").strip():
            errors.append(f"{tag} must end on a cliffhanger (non-empty `cliffhanger`)")
        if i > 1 and not (p.get("recap") or "").strip():
            errors.append(f"{tag} needs a one-sentence `recap` for its 'previously' opening")
        bad_cast = [c for c in p.get("cast", []) if c not in cast_ids]
        if bad_cast:
            errors.append(f"{tag}: unknown cast ids {bad_cast}; use only {sorted(cast_ids)}")
        if p.get("location") not in loc_ids:
            errors.append(f"{tag}: unknown location '{p.get('location')}'; use one of {sorted(loc_ids)}")
        if len((p.get("hook") or "").split()) > 30:
            errors.append(f"{tag}: the hook must be short enough to land in 1-2 seconds")
    return errors


def arc_prompt(bible: dict, idea: str, parts: int, existing_arcs: list[dict]) -> str:
    log = bible.get("continuity_log", [])
    open_threads = [t for e in log[-6:] for t in e.get("open_threads", [])][-10:]
    return "Plan this arc.\n" + json.dumps({
        "idea": idea,
        "parts": parts,
        "series_bible": {k: bible.get(k) for k in ("title", "logline", "world", "characters", "relationships",
                                                   "running_gags", "locations", "format")},
        "continuity_log": [{k: e.get(k) for k in ("episode_id", "title", "summary", "changes", "open_threads",
                                                  "object_states", "character_states")} for e in log[-10:]],
        "open_threads": open_threads,
        "previous_arcs": [{"title": a.get("title"), "final_payoff": a.get("final_payoff")} for a in existing_arcs][-8:],
    }, ensure_ascii=False, indent=1)


def normalize_arc(arc: dict, idea: str) -> dict:
    arc["idea"] = (idea or arc.get("idea") or "")[:1000]
    for i, p in enumerate(arc.get("parts", []), start=1):
        p["part"] = i
        if i == 1:
            p["recap"] = None
        if i == len(arc["parts"]):
            p["cliffhanger"] = None
        p["title"] = (p.get("title") or f"Part {i}")[:80]
    return arc


def plan_arc(project, idea: str, parts: int = 2, llm=None, variation: int = 0, save: bool = True) -> dict:
    """Plan a `parts`-part arc for `idea`, save it, register it in the bible and create the episodes."""
    from storyforge.config import get_settings
    from storyforge.providers.llm import get_llm

    if not 2 <= int(parts) <= 5:
        raise ValueError("an arc has 2 to 5 parts")
    parts = int(parts)
    llm = llm or get_llm(get_settings())
    bible = project.bible()
    cast_ids = {c["id"] for c in bible.get("characters", [])}
    registered = set(project.cast())
    if registered:  # characters need a cast entry (look, rig, voice) to be animated
        cast_ids &= registered
    loc_ids = {loc["id"] for loc in bible.get("locations", [])}

    def check(doc):
        return arc_semantic_errors(doc, parts, cast_ids, loc_ids)

    arc = llm.generate_json("arc_plan", ARC_SYSTEM, arc_prompt(bible, idea, parts, project.arcs()), "arc",
                            semantic_check=check, max_tokens=12000, variation=variation,
                            context={"idea": idea, "parts": parts, "bible": bible})
    arc = normalize_arc(arc, idea)
    proposed = arc.get("arc_id") or ""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", proposed) or project.arc(proposed) is not None:
        arc.pop("arc_id", None)  # save_arc derives a unique id from the title
    if not save:
        return arc
    arc = project.save_arc(arc)
    project.create_arc_episodes(arc)
    return arc
