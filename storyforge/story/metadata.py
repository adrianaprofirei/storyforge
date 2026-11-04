"""Title / description / hashtag suggestions written in the series tone."""

from __future__ import annotations

import json

METADATA_SYSTEM = """You write publishing metadata for one part of an original animated mini-series of
vertical shorts. Match the series tone, stay kid-safe, never mention real brands or people, never
use clickbait lies. Give 3-5 title options (<= 60 characters, the first one is the best), one short
description (2-3 sentences, ends with an invitation to watch the next part unless it is the finale),
and 6-12 hashtags (#CamelCase, no spaces). Reply with JSON only."""


def generate_metadata(llm, screenplay: dict, bible: dict) -> dict:
    user = json.dumps({"series": bible.get("title"), "tone": bible.get("world", {}).get("tone"),
                       "audience": bible.get("world", {}).get("target_audience"),
                       "part": screenplay.get("part"), "title": screenplay.get("title"),
                       "logline": screenplay.get("logline"), "hook": screenplay.get("hook"),
                       "cliffhanger": screenplay.get("cliffhanger"),
                       "beats": [{"speaker": b.get("speaker"), "line": b.get("line"), "action": b.get("action")}
                                 for b in screenplay.get("beats", [])]}, ensure_ascii=False)
    try:
        return llm.generate_json("metadata", METADATA_SYSTEM, user, "metadata", max_tokens=4000,
                                 context={"screenplay": screenplay, "bible": bible})
    except Exception:
        from storyforge.story.demo_writer import template_metadata

        return template_metadata(screenplay, bible)
