"""JSON Schema validation of every document the LLM produces, plus retry-on-invalid."""

from __future__ import annotations

import copy

import pytest

from storyforge.config import ASSETS_DIR
from storyforge.providers.llm.base import ChatReply, LLMProvider, extract_json
from storyforge.schemas import ValidationFailed, get_schema, schema_errors
from storyforge.story.screenplay_tools import semantic_errors
from storyforge.util.io import read_json, read_yaml

SAMPLES = ASSETS_DIR / "samples"


@pytest.fixture(scope="module")
def bible():
    return read_yaml(SAMPLES / "bible.yaml")


@pytest.fixture(scope="module")
def part1():
    return read_json(SAMPLES / "screenplays" / "part1.json")


def test_sample_documents_validate(bible, part1):
    assert schema_errors("bible", bible) == []
    assert schema_errors("screenplay", part1) == []
    assert schema_errors("screenplay", read_json(SAMPLES / "screenplays" / "part2.json")) == []
    assert schema_errors("arc", read_json(SAMPLES / "arc.json")) == []
    for entry in read_yaml(SAMPLES / "cast.yaml").values():
        assert schema_errors("cast_member", entry) == []


@pytest.mark.parametrize("mutate, fragment", [
    (lambda sp: sp["beats"][0].update(emotion="furious_rage"), "emotion"),
    (lambda sp: sp["beats"][0].pop("action"), "action"),
    (lambda sp: sp["beats"][0].update(id="beat-1"), "id"),
    (lambda sp: sp["beats"][0].update(intensity=1.7), "intensity"),
    (lambda sp: sp["beats"][0].update(camera_hint="drone_flyby"), "camera_hint"),
    (lambda sp: sp.update(time_of_day="teatime"), "time_of_day"),
    (lambda sp: sp["beats"][0].update(props=[{"character": "milo", "prop": "laser_sword", "action": "use"}]), "prop"),
])
def test_invalid_screenplays_are_rejected(part1, mutate, fragment):
    sp = copy.deepcopy(part1)
    mutate(sp)
    errors = schema_errors("screenplay", sp)
    assert errors, "expected a schema error"
    assert any(fragment in e for e in errors), errors


def test_semantic_checks_catch_unknown_cast_and_location(bible, part1):
    sp = copy.deepcopy(part1)
    sp["beats"][1]["speaker"] = "nobody"
    sp["location"] = "moon_base"
    cast = {c["id"] for c in bible["characters"]}
    locs = {loc["id"] for loc in bible["locations"]}
    errors = semantic_errors(sp, bible, cast, locs)
    assert any("nobody" in e for e in errors)
    assert any("moon_base" in e for e in errors)


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('Sure! ```json\n{"a": 1}\n``` done') == {"a": 1}
    assert extract_json('prefix {"a": {"b": "}"}} suffix') == {"a": {"b": "}"}}
    with pytest.raises(ValueError):
        extract_json("no json here")


class ScriptedLLM(LLMProvider):
    """Replies from a list; records the conversation it was sent."""

    name = "scripted"
    model = "test"

    def __init__(self, replies):
        super().__init__(max_attempts=3)
        self.replies = list(replies)
        self.seen = []

    def chat(self, system, messages, schema, max_tokens):
        self.seen.append([dict(m) for m in messages])
        return ChatReply(text=self.replies.pop(0))


def test_generate_json_retries_with_validation_feedback():
    good = '{"summary": "ok", "changes": {"relationships": [], "objects": [], "secrets": [], "facts": []}}'
    llm = ScriptedLLM(['{"summary": 5}', good])
    doc = llm.generate_json("continuity_log", "sys", "user", "continuity")
    assert doc["summary"] == "ok"
    assert llm.calls[-1].attempts == 2
    # the second request carries the first reply and the list of problems
    second = llm.seen[1]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert "did not pass validation" in second[2]["content"] and "changes" in second[2]["content"]


def test_generate_json_gives_up_after_max_attempts():
    llm = ScriptedLLM(['{"summary": 1}'] * 3)
    with pytest.raises(ValidationFailed):
        llm.generate_json("continuity_log", "sys", "user", "continuity")


def test_semantic_check_failures_are_retried_too():
    good = '{"summary": "fine", "changes": {"relationships": [], "objects": [], "secrets": [], "facts": []}}'
    bad = '{"summary": "mentions roblox", "changes": {"relationships": [], "objects": [], "secrets": [], "facts": []}}'
    llm = ScriptedLLM([bad, good])
    doc = llm.generate_json("continuity_log", "sys", "u", "continuity",
                            semantic_check=lambda d: ["no brands"] if "roblox" in d["summary"] else [])
    assert doc["summary"] == "fine"


def test_structured_output_schema_subset():
    from storyforge.providers.llm.anthropic_llm import structured_schema

    ss = structured_schema(get_schema("screenplay"))
    text = repr(ss)
    for kw in ("maxLength", "minLength", "minimum", "maximum", "pattern", "maxItems", "uniqueItems", "$schema"):
        assert f"'{kw}'" not in text, kw

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            assert not isinstance(node.get("type"), list), "type arrays must become anyOf"
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(ss)
