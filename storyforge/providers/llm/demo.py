"""Offline demo LLM: deterministic documents from the bundled samples / templates."""

from __future__ import annotations

from storyforge.config import Settings
from storyforge.providers.llm.base import LLMCall, LLMProvider
from storyforge.schemas import ValidationFailed, schema_errors


class DemoLLM(LLMProvider):
    name = "demo"
    model = "offline-templates"

    def __init__(self, settings: Settings):
        super().__init__(max_attempts=1)

    def chat(self, system, messages, schema, max_tokens):  # pragma: no cover - not used
        raise NotImplementedError("demo provider only supports generate_json")

    def generate_json(self, task, system, user, schema_name, semantic_check=None, max_tokens=16000, context=None):
        from storyforge.story.demo_writer import demo_generate

        doc = demo_generate(task, context or {})
        errors = schema_errors(schema_name, doc)
        if not errors and semantic_check:
            errors = semantic_check(doc)
        self.calls.append(LLMCall(task, 1, [errors] if errors else [], self.name, self.model))
        if errors and schema_errors(schema_name, doc):
            raise ValidationFailed(errors)
        return doc
