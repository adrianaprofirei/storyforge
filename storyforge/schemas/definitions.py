"""Schema definitions (draft 2020-12)."""

from __future__ import annotations

from storyforge.models.constants import (
    BEAT_TYPES,
    CAMERA_MOVES,
    EMOTION_FX,
    EMOTIONS,
    GESTURES,
    LOCOMOTION,
    MUSIC_MOODS,
    PACES,
    PROP_ACTIONS,
    PROPS,
    SHOT_TYPES,
    STYLE_PRESETS,
    TIMES_OF_DAY,
    VOLUMES,
)

ID = {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,39}$"}
NULLABLE_ID = {"type": ["string", "null"], "pattern": "^[a-z][a-z0-9_]{0,39}$"}

CAMERA_HINTS = sorted(set(SHOT_TYPES + CAMERA_MOVES + ["low_angle", "high_angle", "pov", "reaction"]))

BEAT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "speaker", "line", "emotion", "intensity", "action", "performance_note"],
    "properties": {
        "id": {"type": "string", "pattern": "^b[0-9]{2,3}$", "description": "Beat id, e.g. b01"},
        "speaker": {**NULLABLE_ID, "description": "Cast id of the speaker, null for a silent action beat"},
        "addressee": {**NULLABLE_ID, "description": "Who the line is said to (drives eyelines)"},
        "line": {"type": "string", "maxLength": 240, "description": "Spoken dialogue; empty for action beats"},
        "emotion": {"enum": EMOTIONS},
        "intensity": {"type": "number", "minimum": 0, "maximum": 1},
        "action": {"type": "string", "maxLength": 320, "description": "What we see happen"},
        "performance_note": {"type": "string", "maxLength": 220, "description": "Acting/voice direction"},
        "camera_hint": {"anyOf": [{"enum": CAMERA_HINTS}, {"type": "null"}]},
        "beat_type": {"enum": BEAT_TYPES},
        "gesture": {"anyOf": [{"enum": GESTURES}, {"type": "null"}]},
        "motion": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type"],
                    "properties": {
                        "type": {"enum": LOCOMOTION},
                        "character": NULLABLE_ID,
                        "to": {"type": ["string", "null"], "maxLength": 40},
                        "side": {"enum": ["left", "right", "back", "front", None]},
                    },
                },
            ]
        },
        "props": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["character", "prop", "action"],
                "properties": {
                    "character": ID,
                    "prop": {"enum": PROPS},
                    "action": {"enum": PROP_ACTIONS},
                    "to": NULLABLE_ID,
                },
            },
        },
        "fx": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "additionalProperties": False, "required": ["character", "type"],
            "properties": {"character": ID, "type": {"enum": EMOTION_FX}}}},
        "sfx": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 40}},
        "delivery": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"pace": {"enum": PACES}, "volume": {"enum": VOLUMES}},
        },
    },
}

SCREENPLAY = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://storyforge.dev/schemas/screenplay.schema.json",
    "title": "StoryForge screenplay (one part of an arc)",
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "cast", "location", "time_of_day", "beats"],
    "properties": {
        "schema_version": {"const": 1},
        "episode_id": {"type": "string", "maxLength": 60},
        "title": {"type": "string", "minLength": 1, "maxLength": 80},
        "logline": {"type": "string", "maxLength": 300},
        "part": {"type": "integer", "minimum": 1, "maximum": 5},
        "cast": {"type": "array", "minItems": 1, "maxItems": 6, "uniqueItems": True, "items": ID},
        "location": ID,
        "time_of_day": {"enum": TIMES_OF_DAY},
        "music_mood": {"enum": MUSIC_MOODS},
        "hook": {"type": "string", "maxLength": 200, "description": "What grabs the viewer in the first 1-2 s"},
        "mini_payoff": {"type": "string", "maxLength": 240},
        "cliffhanger": {"type": ["string", "null"], "maxLength": 240},
        "beats": {"type": "array", "minItems": 3, "maxItems": 40, "items": BEAT},
    },
}

PART_PLAN = {
    "type": "object",
    "additionalProperties": False,
    "required": ["part", "title", "logline", "hook", "escalation", "mini_payoff", "cliffhanger", "location",
                 "time_of_day", "cast"],
    "properties": {
        "part": {"type": "integer", "minimum": 1, "maximum": 5},
        "title": {"type": "string", "maxLength": 80},
        "logline": {"type": "string", "maxLength": 300},
        "hook": {"type": "string", "maxLength": 200},
        "escalation": {"type": "string", "maxLength": 300},
        "mini_payoff": {"type": "string", "maxLength": 240},
        "cliffhanger": {"type": ["string", "null"], "maxLength": 240},
        "recap": {"type": ["string", "null"], "maxLength": 200},
        "location": ID,
        "time_of_day": {"enum": TIMES_OF_DAY},
        "cast": {"type": "array", "minItems": 1, "maxItems": 6, "items": ID},
        "music_mood": {"enum": MUSIC_MOODS},
    },
}

ARC = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://storyforge.dev/schemas/arc.schema.json",
    "title": "StoryForge arc plan",
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "idea", "premise", "parts", "final_payoff"],
    "properties": {
        "arc_id": {"type": "string", "maxLength": 60},
        "title": {"type": "string", "maxLength": 80},
        "idea": {"type": "string", "maxLength": 1000},
        "premise": {"type": "string", "maxLength": 600},
        "theme": {"type": "string", "maxLength": 200},
        "final_payoff": {"type": "string", "maxLength": 400},
        "parts": {"type": "array", "minItems": 2, "maxItems": 5, "items": PART_PLAN},
    },
}

REVIEW = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://storyforge.dev/schemas/review.schema.json",
    "title": "Story editor review of a screenplay",
    "type": "object",
    "additionalProperties": False,
    "required": ["scores", "notes", "rewrites"],
    "properties": {
        "scores": {
            "type": "object",
            "additionalProperties": False,
            "required": ["hook", "clarity", "pacing", "voice", "ending"],
            "properties": {k: {"type": "number", "minimum": 0, "maximum": 10}
                           for k in ["hook", "clarity", "pacing", "voice", "ending"]},
        },
        "notes": {"type": "array", "maxItems": 20, "items": {
            "type": "object", "additionalProperties": False, "required": ["beat_id", "category", "note"],
            "properties": {
                "beat_id": {"type": ["string", "null"]},
                "category": {"enum": ["hook", "clarity", "pacing", "voice", "ending", "continuity", "safety"]},
                "note": {"type": "string", "maxLength": 400},
            }}},
        "rewrites": {"type": "array", "maxItems": 20, "items": BEAT,
                     "description": "Full replacement beats (same id) for weak beats"},
        "insert_after": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False, "required": ["after", "beat"],
            "properties": {"after": {"type": "string"}, "beat": BEAT}}},
        "remove": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
    },
}

CONTINUITY_ENTRY = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://storyforge.dev/schemas/continuity.schema.json",
    "title": "Continuity log entry written after an episode renders",
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "changes"],
    "properties": {
        "summary": {"type": "string", "maxLength": 700},
        "changes": {
            "type": "object",
            "additionalProperties": False,
            "required": ["relationships", "objects", "secrets", "facts"],
            "properties": {
                "relationships": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 240}},
                "objects": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 240}},
                "secrets": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 240}},
                "facts": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 240}},
            },
        },
        "open_threads": {"type": "array", "maxItems": 10, "items": {"type": "string", "maxLength": 240}},
    },
}

CONTINUITY_CHECK = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://storyforge.dev/schemas/continuity_check.schema.json",
    "title": "Contradictions between a screenplay and the series bible",
    "type": "object",
    "additionalProperties": False,
    "required": ["issues"],
    "properties": {
        "issues": {"type": "array", "maxItems": 30, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["beat_id", "kind", "severity", "message"],
            "properties": {
                "beat_id": {"type": ["string", "null"]},
                "kind": {"enum": ["relationship", "forgotten_event", "out_of_character", "object", "secret",
                                  "location", "content_rule", "other"]},
                "severity": {"enum": ["info", "warning", "error"]},
                "message": {"type": "string", "maxLength": 400},
                "suggestion": {"type": ["string", "null"], "maxLength": 400},
            }}},
    },
}

METADATA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://storyforge.dev/schemas/metadata.schema.json",
    "title": "Title/description/hashtag suggestions for one part",
    "type": "object",
    "additionalProperties": False,
    "required": ["titles", "description", "hashtags"],
    "properties": {
        "titles": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string", "maxLength": 100}},
        "description": {"type": "string", "maxLength": 600},
        "hashtags": {"type": "array", "minItems": 3, "maxItems": 15,
                     "items": {"type": "string", "pattern": "^#[A-Za-z0-9_]{2,40}$"}},
    },
}

COLOR = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}

CHARACTER_LOOK = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "body": {"type": "object", "additionalProperties": {"type": "number", "minimum": 0.3, "maximum": 2.5}},
        "colors": {"type": "object", "additionalProperties": COLOR},
        "hair": {"type": "object"},
        "accessories": {"type": "array", "items": {"type": "object", "required": ["type"]}},
        "clothing": {"type": "object"},
        "face": {"type": "object"},
    },
}

CAST_MEMBER = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://storyforge.dev/schemas/cast_member.schema.json",
    "title": "Cast registry entry",
    "type": "object",
    "required": ["id", "name", "kind", "look", "voice"],
    "additionalProperties": True,
    "properties": {
        "id": ID,
        "name": {"type": "string", "minLength": 1, "maxLength": 40},
        "kind": {"enum": ["procedural", "imported"]},
        "look": CHARACTER_LOOK,
        "rig": {"type": "object"},
        "voice": {"type": "object"},
        "settings": {"type": "object"},
        "import": {"type": ["object", "null"], "properties": {
            "file": {"type": "string"}, "bone_map": {"type": "object"}, "face": {"type": "object"},
            "scale": {"type": "number"}}},
    },
}

BIBLE = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://storyforge.dev/schemas/bible.schema.json",
    "title": "StoryForge series bible",
    "type": "object",
    "required": ["series_id", "title", "world", "characters", "locations"],
    "additionalProperties": True,
    "properties": {
        "series_id": ID,
        "title": {"type": "string", "maxLength": 80},
        "version": {"type": "integer", "minimum": 1},
        "logline": {"type": "string"},
        "world": {
            "type": "object",
            "required": ["setting", "tone", "target_audience", "content_rules", "visual_style"],
            "properties": {
                "setting": {"type": "string"},
                "tone": {"type": "string"},
                "target_audience": {"type": "string"},
                "content_rules": {"type": "array", "items": {"type": "string"}},
                "visual_style": {"enum": STYLE_PRESETS},
            },
        },
        "format": {"type": "object"},
        "look": {"type": "object"},
        "characters": {"type": "array", "minItems": 1, "items": {
            "type": "object",
            "required": ["id", "name", "personality"],
            "properties": {
                "id": ID, "name": {"type": "string"}, "cast_ref": {"type": "string"},
                "role": {"type": "string"},
                "personality": {"type": "string"}, "speech_patterns": {"type": "string"},
                "catchphrases": {"type": "array", "items": {"type": "string"}},
                "wants": {"type": "string"}, "fears": {"type": "string"},
                "voice_direction": {"type": "string"},
            },
        }},
        "relationships": {"type": "array", "items": {
            "type": "object", "required": ["a", "b", "type"],
            "properties": {"a": ID, "b": ID, "type": {"type": "string"}, "notes": {"type": "string"}}}},
        "running_gags": {"type": "array", "items": {"type": "object", "required": ["id", "description"]}},
        "locations": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["id", "name", "preset"],
            "properties": {"id": ID, "name": {"type": "string"}, "preset": {"type": "string"},
                           "description": {"type": "string"}}}},
        "arcs": {"type": "array", "items": {"type": "object"}},
        "episodes": {"type": "array", "items": {"type": "object"}},
        "continuity_log": {"type": "array", "items": {"type": "object"}},
    },
}

ALL_SCHEMAS = {
    "screenplay": SCREENPLAY,
    "arc": ARC,
    "review": REVIEW,
    "continuity": CONTINUITY_ENTRY,
    "continuity_check": CONTINUITY_CHECK,
    "metadata": METADATA,
    "cast_member": CAST_MEMBER,
    "bible": BIBLE,
}
