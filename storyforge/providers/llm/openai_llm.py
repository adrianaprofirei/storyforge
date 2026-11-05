"""OpenAI provider over the REST Chat Completions API (httpx, no SDK dependency).

Design decisions:
* Chat Completions is the most widely implemented endpoint, so OPENAI_BASE_URL can also point at
  Azure OpenAI proxies or local OpenAI-compatible servers (Ollama, LM Studio, vLLM).
* JSON mode (`response_format: {"type": "json_object"}`) with the task's JSON Schema in the system
  prompt. Strict `json_schema` mode would require every property to be required, which our
  schemas (optional beat fields) do not satisfy; the base class validates locally and retries with
  the errors instead.
* `max_completion_tokens` (reasoning models) with automatic fallback to `max_tokens`, and optional
  OPENAI_REASONING_EFFORT; parameters a compatible server rejects are dropped once and remembered.
* Retries 429/5xx/network errors with exponential backoff honouring `retry-after`; refusals and
  content-filter stops raise LLMRefused, `finish_reason == "length"` raises LLMTruncated.
"""

from __future__ import annotations

import json
import logging
import random
import time

import httpx

from storyforge.config import Settings
from storyforge.providers.llm.base import ChatReply, LLMError, LLMProvider, LLMRefused, LLMTruncated

log = logging.getLogger("storyforge.llm.openai")

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class OpenAILLM(LLMProvider):
    name = "openai"
    max_output_tokens = 100000

    def __init__(self, settings: Settings):
        super().__init__(max_attempts=settings.llm_max_attempts, cache_dir=settings.data_dir / "cache" / "llm")
        self.model = settings.openai_model or "gpt-5.5"
        self.base_url = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        self.reasoning_effort = settings.openai_reasoning_effort or None
        self.http = httpx.Client(timeout=httpx.Timeout(900.0, connect=20.0),
                                 headers={"Authorization": f"Bearer {settings.openai_api_key}",
                                          "Content-Type": "application/json"})
        self._token_param = "max_completion_tokens"
        self._dropped: set[str] = set()

    def describe(self) -> dict:
        return {"provider": self.name, "model": self.model, "base_url": self.base_url,
                "reasoning_effort": self.reasoning_effort}

    def _body(self, system: str, messages: list[dict], schema: dict | None, max_tokens: int) -> dict:
        sys_text = system or "You are a helpful writer."
        if schema is not None:
            sys_text += ("\n\nReply with ONE JSON object (no prose, no code fences) that validates against this "
                         "JSON Schema:\n" + json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
        body: dict = {"model": self.model, "messages": [{"role": "system", "content": sys_text}] + [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else str(m["content"])}
            for m in messages]}
        body[self._token_param] = max_tokens
        if schema is not None and "response_format" not in self._dropped:
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort and "reasoning_effort" not in self._dropped:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def _post(self, body: dict) -> dict:
        url = f"{self.base_url}/chat/completions"
        delay = 2.0
        for attempt in range(5):
            try:
                r = self.http.post(url, json=body)
            except httpx.TimeoutException as exc:
                err: Exception = LLMError(f"OpenAI request timed out: {exc}")
            except httpx.HTTPError as exc:
                err = LLMError(f"cannot reach {self.base_url}: {exc}")
            else:
                if r.status_code < 400:
                    return r.json()
                text = r.text[:600]
                if r.status_code == 400:
                    return {"_bad_request": text}
                if r.status_code == 401:
                    raise LLMError("OPENAI_API_KEY was rejected (401); check the key in .env")
                if r.status_code == 403:
                    raise LLMError(f"OpenAI denied access to {self.model} (403): {text}")
                if r.status_code == 404:
                    raise LLMError(f"model '{self.model}' or endpoint not found (404); check OPENAI_MODEL / "
                                   f"OPENAI_BASE_URL: {text}")
                if r.status_code not in RETRY_STATUS:
                    raise LLMError(f"OpenAI API error {r.status_code}: {text}")
                err = LLMError(f"OpenAI API error {r.status_code}: {text}")
                ra = r.headers.get("retry-after")
                if ra:
                    try:
                        delay = max(delay, float(ra))
                    except ValueError:
                        pass
            if attempt == 4:
                raise err
            time.sleep(min(60.0, delay) + random.uniform(0, 0.5))
            delay *= 2
        raise LLMError("unreachable")

    def chat(self, system, messages, schema, max_tokens) -> ChatReply:
        for _ in range(4):
            data = self._post(self._body(system, messages, schema, max_tokens))
            bad = data.get("_bad_request")
            if bad is None:
                break
            low = bad.lower()
            # adapt once to servers that do not know a parameter, then remember it
            if "max_completion_tokens" in low and self._token_param == "max_completion_tokens":
                self._token_param = "max_tokens"
            elif "reasoning_effort" in low and "reasoning_effort" not in self._dropped:
                self._dropped.add("reasoning_effort")
            elif "response_format" in low and "response_format" not in self._dropped:
                self._dropped.add("response_format")
            else:
                raise LLMError(f"OpenAI rejected the request (400): {bad}")
            log.warning("OpenAI-compatible server rejected a parameter; adapting (%s)", bad[:160])
        else:
            raise LLMError("OpenAI kept rejecting the request")
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        finish = choice.get("finish_reason")
        if msg.get("refusal"):
            raise LLMRefused(f"the model declined: {msg['refusal']}")
        if finish == "content_filter":
            raise LLMRefused("the reply was stopped by the content filter")
        if finish == "length":
            raise LLMTruncated(f"reply hit the token limit ({max_tokens})")
        text = msg.get("content") or ""
        usage = data.get("usage") or {}
        return ChatReply(text=text, assistant_content=text,
                         usage={"input_tokens": usage.get("prompt_tokens", 0),
                                "output_tokens": usage.get("completion_tokens", 0)},
                         served_model=data.get("model", self.model))
