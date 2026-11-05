"""Screenplay writer: one part of an arc -> schema-validated screenplay JSON."""

from __future__ import annotations

import json

from storyforge.models.constants import (
    CAMERA_MOVES,
    EMOTION_FX,
    EMOTIONS,
    GESTURES,
    LOCOMOTION,
    PROPS,
    SHOT_TYPES,
)
from storyforge.story.screenplay_tools import semantic_errors

SCREENPLAY_SYSTEM = f"""You are the head writer of an original animated series of vertical (9:16) shorts.
Write ONE part of a multi-part arc as a screenplay in JSON that matches the provided JSON Schema.

Hard rules:
- Runtime: the part must play in {{min_s}}-{{max_s}} seconds. Plan ~2.6 spoken words per second plus
  ~1.5 s per silent action beat. Aim for 14-22 beats.
- Beat 1 is the HOOK and must grab the viewer within 1-2 seconds: a short, striking line (<= 10 words)
  and/or a surprising action. beat_type="hook".
- Build a clear escalation, deliver a satisfying mini-payoff (beat_type "payoff" or "joke"), and
  {{ending_rule}}
- Lines are short (mostly under 14 words), punchy, and unmistakably in each character's voice
  (personality, speech patterns, catchphrases from the bible). No dead air: at most two silent
  beats in a row.
- Every beat has speaker (cast id, or null for a silent action beat), line ("" when silent),
  emotion (one of {", ".join(EMOTIONS)}), intensity 0-1, a visual action, a performance note,
  and optionally: addressee (who is spoken to), camera_hint ({", ".join(SHOT_TYPES + CAMERA_MOVES)}),
  gesture ({", ".join(GESTURES)}), motion ({", ".join(LOCOMOTION)}), props
  ({", ".join(PROPS)}), fx ({", ".join(EMOTION_FX)}), sfx tags, delivery (pace, volume).
- Use ONLY cast ids and location ids from the bible. Respect every content rule of the bible
  (kid-safe, no violence, no real brands/logos/people). Stay consistent with the continuity log.
- Use structured fields (gesture, props, fx, motion) whenever the action implies them; the
  animation system relies on them.
Reply with the JSON document only."""


def screenplay_prompt(bible: dict, arc: dict, part_plan: dict, previous_summary: str | None,
                      continuity: list[dict] | None = None) -> tuple[str, str]:
    fmt = bible.get("format", {})
    total = len(arc.get("parts", []))
    final = part_plan["part"] >= total
    ending = ("this is the FINALE: end on the arc's final payoff and a warm button (beat_type payoff/resolution)."
              if final else "END ON A CLIFFHANGER: the last beat(s) beat_type='cliffhanger', unresolved.")
    system = (SCREENPLAY_SYSTEM.replace("{min_s}", str(fmt.get("part_min_seconds", 45)))
              .replace("{max_s}", str(fmt.get("part_max_seconds", 90))).replace("{ending_rule}", ending))
    user = json.dumps({
        "series_bible": {k: bible.get(k) for k in ("title", "logline", "world", "characters", "relationships",
                                                   "running_gags", "locations")},
        "continuity_log": [{k: e.get(k) for k in ("episode_id", "title", "summary", "changes", "open_threads",
                                                  "object_states", "character_states")}
                           for e in (continuity if continuity is not None else bible.get("continuity_log", []))[-8:]],
        "arc": {k: arc.get(k) for k in ("title", "premise", "theme", "final_payoff")},
        "all_parts": arc.get("parts"),
        "write_part": part_plan,
        "previously": previous_summary,
        "parts_total": total,
    }, ensure_ascii=False, indent=1)
    return system, "Write this part.\n" + user


def write_screenplay(llm, bible: dict, arc: dict, part_plan: dict, cast_ids: set[str],
                     previous_summary: str | None = None, continuity: list[dict] | None = None,
                     variation: int = 0) -> dict:
    system, user = screenplay_prompt(bible, arc, part_plan, previous_summary, continuity)
    loc_ids = {loc["id"] for loc in bible.get("locations", [])}
    fmt = bible.get("format", {})
    rng = (float(fmt.get("part_min_seconds", 45)), float(fmt.get("part_max_seconds", 90)))

    def check(doc):
        return semantic_errors(doc, bible, cast_ids, loc_ids, rng)

    doc = llm.generate_json("screenplay", system, user, "screenplay", semantic_check=check, max_tokens=32000,
                            variation=variation, context={"arc": arc, "part_plan": part_plan, "bible": bible})
    doc["schema_version"] = 1
    doc["part"] = part_plan["part"]
    return doc
