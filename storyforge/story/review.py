"""Script review: deterministic story-editor checks + an LLM story-editor pass.

The rule-based pass always runs (and is the whole review in demo mode). With an LLM, its
findings are given to a second model call acting as a story editor, which scores the
script and rewrites weak beats (validated against ``review.schema.json``).
"""

from __future__ import annotations

import json

from storyforge.story.screenplay_tools import estimated_runtime
from storyforge.util.text import estimate_speech_seconds, split_words


def rule_based_review(sp: dict, bible: dict, is_finale: bool) -> dict:
    notes: list[dict] = []
    beats = sp.get("beats", [])
    scores = {"hook": 8.0, "clarity": 8.0, "pacing": 8.0, "voice": 8.0, "ending": 8.0}

    def note(beat_id, cat, text, penalty):
        notes.append({"beat_id": beat_id, "category": cat, "note": text})
        scores[cat] = max(0.0, scores[cat] - penalty)

    # --- hook (first 1-2 seconds)
    if beats:
        b0 = beats[0]
        words = split_words(b0.get("line", ""))
        first_dur = estimate_speech_seconds(b0.get("line", "")) if words else 1.6
        if b0.get("intensity", 0) < 0.6:
            note(b0["id"], "hook", "Opening beat is low intensity; the first 1-2 s must grab attention.", 3)
        if words and first_dur > 3.2:
            note(b0["id"], "hook", f"Hook line takes ~{first_dur:.1f}s; cut it so the hook lands within 2 s.", 2)
        if not words and not b0.get("action"):
            note(b0["id"], "hook", "Opening beat has neither a line nor a striking action.", 4)
        if b0.get("beat_type") not in (None, "hook", "reveal"):
            note(b0["id"], "hook", "First beat should be the hook (beat_type=hook).", 1)
    # --- clarity
    for b in beats:
        n = len(split_words(b.get("line", "")))
        if n > 22:
            note(b["id"], "clarity", f"Line is {n} words; vertical shorts need short lines (<18 words).", 1.0)
        if b.get("speaker") and not b.get("addressee") and len(sp.get("cast", [])) > 2:
            note(b["id"], "clarity", "Line has no addressee; eyelines will be ambiguous.", 0.3)
    # --- pacing (no dead air)
    silent_run = 0
    for b in beats:
        if not (b.get("line") or "").strip():
            silent_run += 1
            if silent_run >= 3:
                note(b["id"], "pacing", "Three silent beats in a row create dead air.", 2)
        else:
            silent_run = 0
    lows = [b for b in beats if b.get("intensity", 0.5) < 0.3]
    if len(lows) > len(beats) / 3:
        note(None, "pacing", "Too many low-energy beats; raise stakes or cut.", 1.5)
    fmt = bible.get("format", {})
    lo, hi = float(fmt.get("part_min_seconds", 45)), float(fmt.get("part_max_seconds", 90))
    est = estimated_runtime(sp)
    if est < lo:
        note(None, "pacing", f"Estimated runtime {est:.0f}s is under the {lo:.0f}s minimum.", 2)
    if est > hi:
        note(None, "pacing", f"Estimated runtime {est:.0f}s exceeds the {hi:.0f}s maximum.", 2)
    # --- character voice
    chars = {c["id"]: c for c in bible.get("characters", [])}
    for cid in sp.get("cast", []):
        if cid not in chars:
            note(None, "voice", f"'{cid}' is not in the series bible.", 2)
    for b in beats:
        c = chars.get(b.get("speaker") or "")
        if c and "short" in (c.get("speech_patterns", "").lower()) and len(split_words(b.get("line", ""))) > 16:
            note(b["id"], "voice", f"{c['name']} speaks in short sentences; this line is long.", 0.5)
    # --- ending
    if beats:
        last = beats[-1]
        if not is_finale:
            has_cliff = any(b.get("beat_type") == "cliffhanger" for b in beats[-3:])
            if not has_cliff:
                note(last["id"], "ending", "Non-final part must end on a cliffhanger.", 4)
        else:
            if not any(b.get("beat_type") in ("payoff", "resolution") for b in beats[-4:]):
                note(last["id"], "ending", "Finale must end on the arc's payoff/resolution.", 4)
        if not any(b.get("beat_type") in ("payoff", "joke", "reveal") for b in beats):
            note(None, "ending", "No mini-payoff or punchline beat found.", 2)
    return {"scores": {k: round(v, 1) for k, v in scores.items()}, "notes": notes, "rewrites": []}


REVIEW_SYSTEM = """You are the story editor of an animated kids' series made of vertical 45-90 second shorts.
You review one part's screenplay (JSON) against the series bible and hard rules:
- Hook: the first beat must grab attention within 1-2 seconds (short, striking line or action).
- Clarity: every line short (under ~18 words), clear who speaks to whom, nothing confusing.
- Pacing: no dead air, no more than two silent beats in a row, rising stakes.
- Character voice: every line must sound like that character (personality, speech patterns,
  catchphrases) as described in the bible.
- Ending: a satisfying mini-payoff; a cliffhanger last beat unless this is the arc finale, which
  must land the arc's final payoff.
- Content rules of the bible are absolute (kid-safe, no violence, no real brands or people).
Score each category 0-10, write concise notes, and REWRITE weak beats: a rewrite is a full beat
object with the SAME id that replaces the original. Keep beats that already work. You may insert
at most 4 beats and remove at most 6. Reply with JSON only, matching the review schema."""


def llm_review(llm, sp: dict, bible: dict, part_plan: dict | None, findings: dict, is_finale: bool,
               continuity: list[dict] | None = None) -> dict:
    user = json.dumps({
        "bible": {k: bible.get(k) for k in ("title", "world", "characters", "relationships", "running_gags",
                                             "locations", "format")},
        "recent_continuity": [{k: e.get(k) for k in ("episode_id", "summary", "open_threads")}
                              for e in (continuity if continuity is not None else bible.get("continuity_log", []))[-5:]],
        "part_plan": part_plan,
        "is_finale": is_finale,
        "automatic_findings": findings["notes"],
        "screenplay": sp,
    }, ensure_ascii=False, indent=1)
    return llm.generate_json("script_review", REVIEW_SYSTEM, user, "review", max_tokens=24000,
                             context={"screenplay": sp, "findings": findings})
