"""LLM provider interface with schema-validated JSON generation and retry-with-feedback."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from storyforge.schemas import ValidationFailed, get_schema, schema_errors

log = logging.getLogger("storyforge.llm")


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """Raised by the demo provider for tasks that need a real model."""


@dataclass
class LLMCall:
    task: str
    attempts: int
    errors: list[list[str]]
    provider: str
    model: str


def extract_json(text: str):
    """Parse the first JSON object in a model reply (tolerates code fences and prose)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object in reply")


class LLMProvider:
    name = "base"
    model = ""

    def __init__(self, max_attempts: int = 4):
        self.max_attempts = max_attempts
        self.calls: list[LLMCall] = []

    # Providers implement a single chat turn. `messages` alternate user/assistant.
    def chat(self, system: str, messages: list[dict], schema: dict | None, max_tokens: int) -> str:
        raise NotImplementedError

    def generate_json(self, task: str, system: str, user: str, schema_name: str,
                      semantic_check: Callable[[dict], list[str]] | None = None,
                      max_tokens: int = 16000, context: dict | None = None) -> dict:
        """Ask for a JSON document, validate (schema + semantics), retry with the errors."""
        schema = get_schema(schema_name)
        messages = [{"role": "user", "content": user}]
        all_errors: list[list[str]] = []
        for attempt in range(1, self.max_attempts + 1):
            reply = self.chat(system, messages, schema, max_tokens)
            try:
                doc = extract_json(reply)
                errors = schema_errors(schema_name, doc)
                if not errors and semantic_check:
                    errors = semantic_check(doc)
            except ValueError as exc:
                doc, errors = None, [f"reply is not valid JSON: {exc}"]
            if not errors:
                self.calls.append(LLMCall(task, attempt, all_errors, self.name, self.model))
                return doc
            all_errors.append(errors)
            log.warning("%s attempt %d invalid: %s", task, attempt, "; ".join(errors[:5]))
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": (
                "Your JSON did not pass validation. Fix every problem below and reply with the complete "
                "corrected JSON document only (no prose, no code fences).\nProblems:\n- " + "\n- ".join(errors[:25]))})
        self.calls.append(LLMCall(task, self.max_attempts, all_errors, self.name, self.model))
        raise ValidationFailed(all_errors[-1] if all_errors else ["unknown error"])
