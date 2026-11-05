"""LLM provider interface with schema-validated JSON generation and retry-with-feedback.

Every story task (arc plan, screenplay, script review, continuity log/check, metadata) asks for one
JSON document. `generate_json` validates the reply against the task's JSON Schema plus optional
semantic checks and, when it fails, sends the errors back so the model can fix its own document
(up to LLM_MAX_ATTEMPTS). Providers only implement one chat turn (`chat`).

Replies are cached on disk by a hash of (provider, model, system, prompt, schema): re-running a
stage whose prompt did not change costs nothing. Pass `variation` to ask for a fresh take.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from storyforge.schemas import ValidationFailed, get_schema, schema_errors
from storyforge.util.hashing import stable_hash
from storyforge.util.io import read_json, write_json

log = logging.getLogger("storyforge.llm")


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """Raised by the demo provider for tasks that need a real model."""


class LLMRefused(LLMError):
    """The model (and any server-side fallback) declined the request. Not retried with feedback."""


class LLMTruncated(LLMError):
    """The reply hit the output-token limit; the caller retries with a larger budget."""


@dataclass
class ChatReply:
    text: str
    # what to send back as the assistant turn when asking for a correction (provider specific:
    # Anthropic echoes the content blocks unchanged, OpenAI the message text)
    assistant_content: object = None
    usage: dict = field(default_factory=dict)
    served_model: str = ""


@dataclass
class LLMCall:
    task: str
    attempts: int
    errors: list[list[str]]
    provider: str
    model: str
    usage: dict = field(default_factory=dict)
    served_model: str = ""
    cached: bool = False


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


def _add_usage(total: dict, usage: dict) -> None:
    for k, v in (usage or {}).items():
        if isinstance(v, int | float):
            total[k] = total.get(k, 0) + v


class LLMProvider:
    name = "base"
    model = ""
    # largest max_tokens a truncated reply may be retried with
    max_output_tokens = 64000

    def __init__(self, max_attempts: int = 4, cache_dir: Path | None = None):
        self.max_attempts = max_attempts
        self.calls: list[LLMCall] = []
        self.cache_dir = cache_dir

    # Providers implement a single chat turn. `messages` alternate user/assistant.
    def chat(self, system: str, messages: list[dict], schema: dict | None, max_tokens: int) -> ChatReply:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"provider": self.name, "model": self.model}

    # ------------------------------------------------------------------ cache
    def _cache_path(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / key[:2] / f"{key}.json"

    def generate_json(self, task: str, system: str, user: str, schema_name: str,
                      semantic_check: Callable[[dict], list[str]] | None = None,
                      max_tokens: int = 16000, context: dict | None = None, cache: bool = True,
                      variation: int = 0) -> dict:
        """Ask for a JSON document, validate (schema + semantics), retry with the errors."""
        schema = get_schema(schema_name)
        if variation:
            user = f"{user}\n\n(Variation #{variation}: write a fresh take, different from earlier drafts.)"
        key = stable_hash({"p": self.name, "m": self.model, "s": system, "u": user, "schema": schema_name,
                           "v": schema.get("$id"), "sh": stable_hash(schema)}, 32)
        cpath = self._cache_path(key) if cache else None
        if cpath and cpath.is_file():
            doc = read_json(cpath, None)
            if isinstance(doc, dict):
                errors = schema_errors(schema_name, doc) or (semantic_check(doc) if semantic_check else [])
                if not errors:
                    self.calls.append(LLMCall(task, 0, [], self.name, self.model, cached=True))
                    return doc
        messages: list[dict] = [{"role": "user", "content": user}]
        all_errors: list[list[str]] = []
        usage: dict = {}
        served = ""
        attempt = 0
        while attempt < self.max_attempts:
            attempt += 1
            try:
                reply = self.chat(system, messages, schema, max_tokens)
            except LLMTruncated as exc:
                if max_tokens >= self.max_output_tokens:
                    raise LLMError(f"{task}: reply still truncated at max_tokens={max_tokens}") from exc
                max_tokens = min(self.max_output_tokens, int(max_tokens * 1.6))
                log.warning("%s attempt %d truncated; retrying with max_tokens=%d", task, attempt, max_tokens)
                all_errors.append([f"reply truncated (max_tokens); retried with {max_tokens}"])
                continue
            _add_usage(usage, reply.usage)
            served = reply.served_model or served
            try:
                doc = extract_json(reply.text)
                errors = schema_errors(schema_name, doc)
                if not errors and semantic_check:
                    errors = semantic_check(doc)
            except ValueError as exc:
                doc, errors = None, [f"reply is not valid JSON: {exc}"]
            if not errors:
                self.calls.append(LLMCall(task, attempt, all_errors, self.name, self.model, usage, served))
                if cpath:
                    write_json(cpath, doc)
                return doc
            all_errors.append(errors)
            log.warning("%s attempt %d invalid: %s", task, attempt, "; ".join(errors[:5]))
            messages.append({"role": "assistant", "content": reply.assistant_content
                             if reply.assistant_content is not None else reply.text})
            messages.append({"role": "user", "content": (
                "Your JSON did not pass validation. Fix every problem below and reply with the complete "
                "corrected JSON document only (no prose, no code fences).\nProblems:\n- " + "\n- ".join(errors[:25]))})
        self.calls.append(LLMCall(task, self.max_attempts, all_errors, self.name, self.model, usage, served))
        raise ValidationFailed(all_errors[-1] if all_errors else ["unknown error"])
