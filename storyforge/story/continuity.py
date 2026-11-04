"""Continuity: the series' memory.

Log. Once a part's script is locked (after the review), the LLM writes a continuity entry: a
summary, what changed (relationships, objects, secrets, facts), open threads, where important
objects ended up (``object_states``) and lasting character changes (``character_states``). It is
upserted into the bible's ``continuity_log`` (a new bible version) and later marked ``rendered``.
The writer of the next part, the arc planner and the recap card all read it.

Check. Before anything is voiced or rendered, the locked script is compared with the bible and the
entries of every *earlier* episode: deterministic rules (object states, the previous part's open
threads, kid-safety and real-brand rules, unknown cast/locations) plus an LLM continuity
supervisor (relationships, forgotten events, out-of-character behaviour, secrets, ...). Errors on
beats the user did not edit by hand are auto-fixed by an LLM beat rewrite; whatever remains is
written to ``continuity.json``, shown in the UI and the quality report, and - with
``format.continuity_gate: block`` in the bible - stops the pipeline.
"""

from __future__ import annotations

import json
import re

from storyforge.schemas import ValidationFailed, schema_errors
from storyforge.util.text import split_words

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
LOST_STATES = {"lost", "broken", "destroyed", "given_away"}
HELD_STATES = {"has", "found", "returned"}
VIOLENCE = re.compile(r"\b(kill(?:s|ed|ing)?|murder\w*|blood(?:y)?|guns?|shoot(?:s|ing)?|shot\s+(?:him|her|them)|"
                      r"stab\w*|knife|knives|weapons?|corpse|dead\s+body)\b", re.I)
BRANDS = re.compile(r"\b(roblox|minecraft|fortnite|disney|pixar|marvel|pok[eé]mon|lego|nintendo|playstation|xbox|"
                    r"coca[- ]?cola|pepsi|mcdonald'?s|nike|adidas|iphone|ipad|youtube|tiktok|instagram|google|"
                    r"amazon|netflix|starbucks|barbie|spongebob|mario)\b", re.I)
STOP = {"about", "after", "again", "their", "there", "these", "those", "which", "while", "where", "would", "could",
        "should", "everyone", "something", "nothing", "really", "right", "still", "other", "being", "every",
        "never", "always", "maybe", "what", "when", "with", "from", "into", "that", "this", "they", "them",
        "then", "than", "have", "just", "only", "over", "under"}

LOG_SYSTEM = """You keep the continuity log of an original animated series of short vertical episodes.
From one finished part's screenplay write:
- summary: 2-4 sentences, past tense, concrete (who did what, what was revealed, how it ended),
- changes: relationships, objects, secrets and facts the audience now knows (short sentences),
- open_threads: unresolved questions / the cliffhanger, phrased so the next part can pay them off,
- object_states: where every story-relevant object ended up (holder cast id or null, status),
- character_states: lasting changes to characters (injuries, new skills, secrets learned, moods).
Only facts established on screen. Reply with JSON only."""

CHECK_SYSTEM = """You are the continuity supervisor of an original animated series. Compare one part's
screenplay with the series bible and the continuity log of EARLIER episodes and list every real
contradiction:
- relationship: characters treat each other against their established relationship,
- forgotten_event: the script ignores or contradicts earlier events (including the previous part's
  cliffhanger, which the next part must pick up),
- out_of_character: a character acts or speaks against their personality, fears, wants or speech
  patterns without a story reason,
- object: an object is used against where it ended up (lost, broken, given away, who holds it),
- secret: a character knows something they could not know yet, or forgets something they learned,
- location: a location contradicts the bible,
- content_rule: the script breaks a content rule of the bible.
Use the beat_id of the offending beat. severity: error = must be fixed before production,
warning = should be fixed, info = worth a look. Give a short concrete suggestion. Automatic
findings are included: confirm, refine or drop them. An empty list is a valid answer.
Reply with JSON only."""

FIX_SYSTEM = """You are the head writer of an original animated series. Some beats of this part's
screenplay contradict the series continuity. Rewrite ONLY the listed beats so every listed problem
disappears, keeping the story, the jokes, each character's voice, the beat ids, the runtime and the
hook / payoff / cliffhanger structure. Return full replacement beat objects (same ids) and one short
note per fix. Reply with JSON only."""


# ------------------------------------------------------------------ helpers
def episode_order(bible: dict) -> list[str]:
    return [e["id"] for e in bible.get("episodes", []) if e.get("id")]


def prior_entries(bible: dict, episode_id: str) -> list[dict]:
    """Continuity entries an episode must respect: those of episodes planned before it."""
    order = episode_order(bible)
    log = [e for e in bible.get("continuity_log", []) if e.get("episode_id") != episode_id]
    if episode_id not in order:
        return log
    earlier = set(order[:order.index(episode_id)])
    return [e for e in log if e.get("episode_id") in earlier or e.get("episode_id") not in order]


def object_state_map(entries: list[dict]) -> dict[str, dict]:
    state: dict[str, dict] = {}
    for e in entries:
        for o in e.get("object_states") or []:
            state[str(o.get("object", "")).lower()] = {**o, "episode_id": e.get("episode_id")}
    return state


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in split_words(text or "") if len(w) >= 5 and w.lower() not in STOP}


def _issue(beat_id, kind, severity, message, suggestion=None, source="rules") -> dict:
    return {"beat_id": beat_id, "kind": kind, "severity": severity, "message": message[:400],
            "suggestion": (suggestion or None) and suggestion[:400], "source": source}


def rule_issues(sp: dict, bible: dict, prior: list[dict], previous_entry: dict | None = None) -> list[dict]:
    """Deterministic continuity and content-rule checks (always run, also in demo mode)."""
    issues: list[dict] = []
    rules = " ".join(bible.get("world", {}).get("content_rules", [])).lower()
    check_violence = any(w in rules for w in ("violence", "weapon", "kid", "hurt"))
    check_brands = any(w in rules for w in ("brand", "logo", "real people", "product"))
    known_cast = {c["id"] for c in bible.get("characters", [])}
    known_locs = {loc["id"] for loc in bible.get("locations", [])}
    for cid in sp.get("cast", []):
        if cid not in known_cast:
            issues.append(_issue(None, "other", "error", f"'{cid}' is not a character of the series bible",
                                 "Add the character to the bible or use an existing one."))
    if sp.get("location") not in known_locs:
        issues.append(_issue(None, "location", "error", f"location '{sp.get('location')}' is not in the bible",
                             "Use a bible location or add this one to the bible first."))
    states = object_state_map(prior)
    holders: dict[str, str | None] = {}
    for b in sp.get("beats", []):
        text = f"{b.get('line', '')} {b.get('action', '')}"
        for ev in b.get("props") or []:
            obj, who, act = ev.get("prop"), ev.get("character"), ev.get("action")
            st = states.get(str(obj).lower())
            if st and obj not in holders and act in ("use", "show", "hold", "give", "put_down"):
                note = f" ({st['note']})" if st.get("note") else ""
                if st.get("status") in LOST_STATES:
                    issues.append(_issue(
                        b["id"], "object", "warning",
                        f"The {obj} was {st['status'].replace('_', ' ')} at the end of {st['episode_id']}{note}, "
                        f"but here {who} {act.replace('_', ' ')}s it.",
                        f"Show the {obj} being found/repaired first, or use a different prop."))
                elif st.get("status") in HELD_STATES and st.get("holder") and st["holder"] != who:
                    issues.append(_issue(
                        b["id"], "object", "info",
                        f"{st['holder']} had the {obj} at the end of {st['episode_id']}; here {who} has it "
                        f"without a hand-over.", f"Add a 'give' from {st['holder']} or let {st['holder']} use it."))
            if act in ("pick_up", "hold", "use", "show"):
                holders[obj] = who
            elif act == "give":
                holders[obj] = ev.get("to")
            elif act in ("put_down", "drop"):
                holders[obj] = None
        if check_violence and (m := VIOLENCE.search(text)):
            issues.append(_issue(b["id"], "content_rule", "error",
                                 f"'{m.group(0)}' breaks the content rules ({'; '.join(bible['world']['content_rules'][:2])})",
                                 "Rephrase without violence or weapons."))
        if check_brands and (m := BRANDS.search(text)):
            issues.append(_issue(b["id"], "content_rule", "error",
                                 f"mentions the real brand/product '{m.group(0)}'; the series uses original names only",
                                 "Replace it with an invented, original name."))
    if previous_entry and previous_entry.get("open_threads"):
        script_words = _keywords(" ".join(f"{b.get('line', '')} {b.get('action', '')}" for b in sp.get("beats", [])))
        script_words |= _keywords(f"{sp.get('logline', '')} {sp.get('hook', '')}")
        for thread in previous_entry["open_threads"][:3]:
            kws = _keywords(thread)
            if kws and not kws & script_words:
                issues.append(_issue(
                    None, "forgotten_event", "warning",
                    f"{previous_entry.get('episode_id')} left the thread '{thread[:160]}' open, but this part never "
                    f"touches it.", "Pick the thread up early (the recap and the hook are natural places)."))
    return issues


def _merge(rules: list[dict], llm_issues: list[dict]) -> list[dict]:
    out = list(llm_issues)
    seen = {(i.get("beat_id"), i.get("kind")) for i in out}
    for i in rules:
        # deterministic hard rules always stay; softer ones only if the LLM did not cover that beat/kind
        if i["severity"] == "error" or (i.get("beat_id"), i["kind"]) not in seen:
            out.append(i)
    for i in out:
        i.setdefault("source", "llm")
    return sorted(out, key=lambda i: (SEVERITY_ORDER.get(i["severity"], 3), i.get("beat_id") or ""))


def _context(sp: dict, bible: dict, prior: list[dict]) -> dict:
    return {
        "series_bible": {k: bible.get(k) for k in ("title", "world", "characters", "relationships", "running_gags",
                                                   "locations")},
        "earlier_episodes": [{k: e.get(k) for k in ("episode_id", "title", "summary", "changes", "open_threads",
                                                    "object_states", "character_states")} for e in prior[-12:]],
        "screenplay": sp,
    }


# ------------------------------------------------------------------ check + auto-fix
def check_and_fix(llm, sp: dict, bible: dict, prior: list[dict], *, previous_entry: dict | None = None,
                  locked_beats: set[str] | None = None, autofix: bool = True,
                  validate=None, log=lambda msg: None) -> tuple[dict, dict]:
    """Returns (report, screenplay). `validate(sp) -> list[str]` guards auto-fixed scripts."""
    from storyforge.providers.llm import LLMError
    from storyforge.story.screenplay_tools import apply_review

    locked_beats = locked_beats or set()
    rules = rule_issues(sp, bible, prior, previous_entry)
    report = {"provider": llm.name, "checked_against": [e.get("episode_id") for e in prior], "auto_fixed": [],
              "llm": None}
    issues = rules
    if llm.name == "demo":
        issues = llm.generate_json("continuity_check", "", "", "continuity_check",
                                   context={"rule_issues": rules})["issues"]
        for i in issues:
            i.setdefault("source", "rules")
    else:
        user = json.dumps({**_context(sp, bible, prior), "automatic_findings": rules}, ensure_ascii=False, indent=1)
        try:
            res = llm.generate_json("continuity_check", CHECK_SYSTEM, user, "continuity_check", max_tokens=12000,
                                    context={"rule_issues": rules})
            issues = _merge(rules, res.get("issues", []))
            report["llm"] = "ok"
        except (LLMError, ValidationFailed) as exc:
            log(f"LLM continuity check failed ({exc}); using rule-based findings")
            report["llm"] = f"failed: {exc}"
    beats = {b["id"] for b in sp.get("beats", [])}
    for i in issues:
        if i.get("beat_id") not in beats:
            i["beat_id"] = None
        i["status"] = "open"
    targets = [i for i in issues if i["severity"] == "error" and i.get("beat_id")
               and i["beat_id"] not in locked_beats]
    if autofix and targets and llm.name != "demo":
        ids = sorted({i["beat_id"] for i in targets})
        user = json.dumps({**_context(sp, bible, prior), "fix_beats": ids,
                           "problems": [{k: i.get(k) for k in ("beat_id", "kind", "message", "suggestion")}
                                        for i in targets]}, ensure_ascii=False, indent=1)

        def fix_check(doc):
            errs = [f"rewrite {rw.get('id')} is not one of the beats to fix {ids}"
                    for rw in doc.get("rewrites", []) if rw.get("id") not in ids]
            if not errs and validate:
                errs = validate(apply_review(sp, {"rewrites": doc.get("rewrites", [])}))
            return errs

        try:
            fix = llm.generate_json("continuity_fix", FIX_SYSTEM, user, "continuity_fix", semantic_check=fix_check,
                                    max_tokens=16000)
            fixed_sp = apply_review(sp, {"rewrites": fix.get("rewrites", [])})
            rewritten = {rw["id"] for rw in fix.get("rewrites", [])}
            still = {(i.get("beat_id"), i["kind"]) for i in rule_issues(fixed_sp, bible, prior, previous_entry)
                     if i["severity"] == "error"}
            for i in targets:
                if i["beat_id"] in rewritten and (i["beat_id"], i["kind"]) not in still:
                    i["status"] = "auto_fixed"
            report["auto_fixed"] = sorted(rewritten)
            report["fix_notes"] = fix.get("notes", [])
            sp = fixed_sp
        except (LLMError, ValidationFailed) as exc:
            log(f"continuity auto-fix failed ({exc}); issues stay open")
            report["autofix_error"] = str(exc)
    for i in issues:
        if i["status"] == "open" and i.get("beat_id") in locked_beats and i["severity"] == "error":
            i["note"] = "beat edited by hand: not auto-fixed"
    open_issues = [i for i in issues if i["status"] == "open"]
    report["issues"] = issues
    report["counts"] = {s: sum(1 for i in open_issues if i["severity"] == s) for s in ("error", "warning", "info")}
    report["passed"] = report["counts"]["error"] == 0
    return report, sp


# ------------------------------------------------------------------ log
def write_log_entry(llm, sp: dict, bible: dict, prior: list[dict]) -> dict:
    user = json.dumps({"series": bible.get("title"), "characters": [
        {k: c.get(k) for k in ("id", "name", "role")} for c in bible.get("characters", [])],
        "earlier_episodes": [{k: e.get(k) for k in ("episode_id", "summary", "object_states")} for e in prior[-6:]],
        "screenplay": sp}, ensure_ascii=False, indent=1)
    doc = llm.generate_json("continuity_log", LOG_SYSTEM, user, "continuity", max_tokens=6000,
                            context={"screenplay": sp})
    errors = schema_errors("continuity", doc)
    if errors:
        raise ValidationFailed(errors)
    return doc
