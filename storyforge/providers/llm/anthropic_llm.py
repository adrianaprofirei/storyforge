"""Anthropic (Claude) provider, built on the official `anthropic` Python SDK.

Design decisions:
* Model: ANTHROPIC_MODEL (default `claude-opus-5-5`). Thinking is adaptive (always on for current
  models; we send `{"type": "adaptive"}` and never `disabled`/`budget_tokens`, which current models
  reject); depth is controlled with ANTHROPIC_EFFORT (low | medium | high | xhigh | max, default
  high - Opus 5.5 would otherwise default to medium). No temperature, no assistant prefill.
* Structured outputs: `output_config.format = {"type": "json_schema", ...}` with a copy of our JSON
  Schema stripped of the keywords structured outputs do not support (string lengths, numeric
  ranges, regex patterns, array sizes). The full schema is still validated locally by
  `LLMProvider.generate_json`, which feeds any violations back to the model. If the API rejects a
  schema, that task falls back to prompt-only JSON for the rest of the session.
* Refusal fallbacks: on by default. ANTHROPIC_FALLBACKS=default sends `fallbacks="default"` with
  the `server-side-fallback-2026-07-01` beta (the API re-runs a declined request on the model
  Anthropic recommends for that refusal category); a comma-separated model list uses the array
  form (`server-side-fallback-2026-06-01`); `off` disables it.
* Always streams (screenplays are long) and reads the result with `get_final_message()`.
* `stop_reason == "refusal"` raises LLMRefused; `max_tokens` raises LLMTruncated (the base class
  retries with a larger budget). SDK exceptions are mapped to LLMError with actionable messages.
* Top-level prompt caching (`cache_control`) makes correction retries cheap.
"""

from __future__ import annotations

import copy
import logging
import re

from storyforge.config import Settings
from storyforge.providers.llm.base import ChatReply, LLMError, LLMProvider, LLMRefused, LLMTruncated

log = logging.getLogger("storyforge.llm.anthropic")

FALLBACK_DEFAULT_BETA = "server-side-fallback-2026-07-01"
FALLBACK_LIST_BETA = "server-side-fallback-2026-06-01"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# models that take adaptive thinking + effort (older ones get neither)
_ADAPTIVE = re.compile(r"^claude-(fable|mythos|opus-5|sonnet-5|haiku-5|opus-4-[678]|sonnet-4-6)")
# models with server-side refusal fallbacks on the Claude API (Haiku has none)
_FALLBACKS = re.compile(r"^claude-(fable-5|mythos-5|opus-5|sonnet-5-5)")
# JSON Schema keywords that structured outputs do not support (validated locally instead)
_UNSUPPORTED = {"$schema", "$id", "title", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                "multipleOf", "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems",
                "minProperties", "maxProperties", "default", "examples"}


def structured_schema(schema: dict) -> dict:
    """Our JSON Schema -> the subset accepted by structured outputs."""

    def conv(node):
        if isinstance(node, list):
            return [conv(n) for n in node]
        if not isinstance(node, dict):
            return node
        node = {k: v for k, v in node.items() if k not in _UNSUPPORTED}
        t = node.get("type")
        if isinstance(t, list):  # {"type": ["string", "null"], ...} -> anyOf
            rest = {k: v for k, v in node.items() if k not in ("type", "description")}
            branches = [conv({"type": x, **(rest if x != "null" else {})}) for x in t]
            out = {"anyOf": branches}
            if "description" in node:
                out["description"] = node["description"]
            return out
        if "enum" in node and None in node["enum"]:
            vals = [v for v in node["enum"] if v is not None]
            out = {"anyOf": [{"enum": vals}, {"type": "null"}]}
            if "description" in node:
                out["description"] = node["description"]
            return out
        out = {}
        for k, v in node.items():
            if k == "properties":
                out[k] = {pk: conv(pv) for pk, pv in v.items()}
            elif k in ("items", "anyOf", "allOf", "oneOf", "$defs", "definitions"):
                out[k] = conv(v) if k != "$defs" and k != "definitions" else {dk: conv(dv) for dk, dv in v.items()}
            else:
                out[k] = v
        if out.get("type") == "object":
            out.setdefault("properties", {})
            out["additionalProperties"] = False
        if "oneOf" in out:  # oneOf is not supported; anyOf is equivalent for our disjoint branches
            out["anyOf"] = out.pop("oneOf")
        return out

    return conv(copy.deepcopy(schema))


def _echo_content(content: list) -> list:
    """Assistant turn to send back with a correction request. Blocks are echoed unchanged, except
    after a mid-output fallback: model-internal blocks before the last `fallback` block are dropped."""
    last_fb = max((i for i, b in enumerate(content) if getattr(b, "type", "") == "fallback"), default=-1)
    if last_fb < 0:
        return list(content)
    keep = []
    for i, b in enumerate(content):
        t = getattr(b, "type", "")
        if i < last_fb and t not in ("text",):
            continue
        if t == "fallback":
            continue
        keep.append(b)
    return keep


class AnthropicLLM(LLMProvider):
    name = "anthropic"
    max_output_tokens = 128000

    def __init__(self, settings: Settings):
        super().__init__(max_attempts=settings.llm_max_attempts, cache_dir=settings.data_dir / "cache" / "llm")
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency of the package
            raise LLMError("the 'anthropic' package is missing: pip install anthropic") from exc
        self._sdk = anthropic
        self.model = settings.anthropic_model or "claude-opus-5-5"
        self.effort = settings.anthropic_effort if settings.anthropic_effort in EFFORTS else "high"
        self.adaptive = bool(_ADAPTIVE.match(self.model))
        fb = (settings.anthropic_fallbacks or "default").strip()
        self.fallbacks: str | list[dict] | None = None
        if fb.lower() not in ("off", "none", "false", "0", ""):
            if fb.lower() == "default":
                self.fallbacks = "default" if _FALLBACKS.match(self.model) else None
            else:
                self.fallbacks = [{"model": m.strip()} for m in fb.split(",") if m.strip()]
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None, max_retries=3,
                                          timeout=anthropic.Timeout(900.0, connect=20.0))
        self._format_ok: dict[str, bool] = {}

    def describe(self) -> dict:
        return {"provider": self.name, "model": self.model, "effort": self.effort if self.adaptive else None,
                "thinking": "adaptive" if self.adaptive else "off",
                "fallbacks": self.fallbacks if isinstance(self.fallbacks, str) else
                [f["model"] for f in self.fallbacks or []] or "off"}

    # ------------------------------------------------------------------ request
    def _request(self, system: str, messages: list[dict], schema: dict | None, max_tokens: int):
        sdk = self._sdk
        params: dict = {"model": self.model, "max_tokens": max_tokens, "system": system or "You are a helpful writer.",
                        "messages": messages, "cache_control": {"type": "ephemeral"}}
        output_config: dict = {}
        if self.adaptive:
            params["thinking"] = {"type": "adaptive"}
            output_config["effort"] = self.effort
        schema_key = (schema or {}).get("$id") or (schema or {}).get("title") or ""
        use_format = schema is not None and self._format_ok.get(schema_key, True)
        if use_format:
            output_config["format"] = {"type": "json_schema", "schema": structured_schema(schema)}
        if output_config:
            params["output_config"] = output_config
        try:
            if self.fallbacks:
                beta = FALLBACK_DEFAULT_BETA if self.fallbacks == "default" else FALLBACK_LIST_BETA
                with self.client.beta.messages.stream(**params, betas=[beta], fallbacks=self.fallbacks) as stream:
                    return stream.get_final_message()
            with self.client.messages.stream(**params) as stream:
                return stream.get_final_message()
        except sdk.BadRequestError as exc:
            msg = str(getattr(exc, "message", exc))
            if use_format and re.search(r"schema|output_config|format", msg, re.I):
                log.warning("structured output schema rejected for %s (%s); using prompt-only JSON", schema_key, msg)
                self._format_ok[schema_key] = False
                return self._request(system, messages, schema, max_tokens)
            raise LLMError(f"Anthropic rejected the request: {msg}") from exc
        except sdk.AuthenticationError as exc:
            raise LLMError("ANTHROPIC_API_KEY was rejected (401); check the key in .env") from exc
        except sdk.PermissionDeniedError as exc:
            raise LLMError(f"the API key may not use {self.model} (403): {getattr(exc, 'message', exc)}") from exc
        except sdk.NotFoundError as exc:
            raise LLMError(f"model '{self.model}' not found (404); check ANTHROPIC_MODEL") from exc
        except sdk.RateLimitError as exc:
            resp = getattr(exc, "response", None)
            retry = resp.headers.get("retry-after", "?") if resp is not None else "?"
            raise LLMError(f"Anthropic rate limit reached after retries (retry after {retry}s)") from exc
        except sdk.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {getattr(exc, 'message', exc)}") from exc
        except sdk.APITimeoutError as exc:
            raise LLMError("Anthropic request timed out; try again or lower ANTHROPIC_EFFORT") from exc
        except sdk.APIConnectionError as exc:
            raise LLMError(f"cannot reach the Anthropic API: {exc}") from exc

    def chat(self, system, messages, schema, max_tokens) -> ChatReply:
        msg = self._request(system, messages, schema, max_tokens)
        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            explanation = getattr(details, "explanation", None) if details else None
            raise LLMRefused(f"Claude declined this request (category: {category or 'unspecified'})"
                             + (f": {explanation}" if explanation else ""))
        if msg.stop_reason == "max_tokens":
            raise LLMTruncated(f"reply hit max_tokens={max_tokens}")
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        u = msg.usage
        usage = {k: getattr(u, k, 0) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                    "cache_creation_input_tokens")}
        served = getattr(msg, "model", self.model) or self.model
        if served != self.model:
            log.info("request served by fallback model %s", served)
        return ChatReply(text=text, assistant_content=_echo_content(msg.content), usage=usage, served_model=served)
