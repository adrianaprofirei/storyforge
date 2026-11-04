"""LLM providers against mocked transports (no network, no keys)."""

from __future__ import annotations

import dataclasses
import json
import types

import httpx
import pytest

from storyforge.config import get_settings
from storyforge.providers.llm.base import LLMRefused

GOOD = {"summary": "x", "changes": {"relationships": [], "objects": [], "secrets": [], "facts": []}}


class _Block:
    def __init__(self, t, text=""):
        self.type, self.text = t, text


def _msg(text, stop="end_turn", model="claude-opus-5-5"):
    usage = types.SimpleNamespace(input_tokens=10, output_tokens=20, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0)
    return types.SimpleNamespace(stop_reason=stop, content=[_Block("thinking"), _Block("text", text)], usage=usage,
                                 model=model, stop_details=types.SimpleNamespace(category="cyber", explanation="no"))


@pytest.fixture()
def anthropic_llm():
    pytest.importorskip("anthropic")
    from storyforge.providers.llm.anthropic_llm import AnthropicLLM

    s = dataclasses.replace(get_settings(), anthropic_api_key="sk-test", anthropic_model="claude-opus-5-5",
                            anthropic_effort="high", anthropic_fallbacks="default")
    llm = AnthropicLLM(s)
    llm.cache_dir = None
    llm.sent, llm.replies = [], []

    class Stream:
        def __init__(self, **kw):
            llm.sent.append(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return llm.replies.pop(0)

    ns = types.SimpleNamespace(stream=lambda **kw: Stream(**kw))
    llm.client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=ns), messages=ns)
    return llm


def test_anthropic_request_shape(anthropic_llm):
    anthropic_llm.replies.append(_msg(json.dumps(GOOD)))
    assert anthropic_llm.generate_json("continuity_log", "sys", "user", "continuity") == GOOD
    req = anthropic_llm.sent[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["thinking"] == {"type": "adaptive"}
    assert req["output_config"]["effort"] == "high"
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["betas"] == ["server-side-fallback-2026-07-01"] and req["fallbacks"] == "default"
    assert "temperature" not in req
    assert req["messages"][-1]["role"] == "user", "no assistant prefill"


def test_anthropic_refusal_and_truncation(anthropic_llm):
    anthropic_llm.replies.append(_msg("", stop="refusal"))
    with pytest.raises(LLMRefused):
        anthropic_llm.generate_json("continuity_log", "sys", "u1", "continuity")
    anthropic_llm.replies += [_msg('{"summ', stop="max_tokens"), _msg(json.dumps(GOOD))]
    anthropic_llm.generate_json("continuity_log", "sys", "u2", "continuity", max_tokens=1000)
    assert anthropic_llm.sent[-1]["max_tokens"] == 1600


def test_anthropic_fallback_settings():
    pytest.importorskip("anthropic")
    from storyforge.providers.llm.anthropic_llm import AnthropicLLM

    base = dataclasses.replace(get_settings(), anthropic_api_key="sk-test", anthropic_model="claude-opus-5-5")
    assert AnthropicLLM(dataclasses.replace(base, anthropic_fallbacks="off")).fallbacks is None
    assert AnthropicLLM(dataclasses.replace(base, anthropic_fallbacks="claude-opus-4-8")).fallbacks == [
        {"model": "claude-opus-4-8"}]
    haiku = AnthropicLLM(dataclasses.replace(base, anthropic_model="claude-haiku-5-5", anthropic_fallbacks="default"))
    assert haiku.fallbacks is None  # no server-side fallback exists for Haiku


def test_openai_provider_adapts_and_retries(monkeypatch):
    import storyforge.providers.llm.openai_llm as mod

    s = dataclasses.replace(get_settings(), openai_api_key="sk-test", openai_model="gpt-5.5", openai_reasoning_effort="")
    llm = mod.OpenAILLM(s)
    llm.cache_dir = None
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        if len(seen) == 1:
            return httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'max_completion_tokens'"}})
        if len(seen) == 2:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(200, json={"model": "gpt-5.5", "usage": {"prompt_tokens": 3, "completion_tokens": 4},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(GOOD)}}]})

    llm.http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    assert llm.generate_json("continuity_log", "sys", "user", "continuity") == GOOD
    assert "max_completion_tokens" in seen[0] and "max_tokens" in seen[1]
    assert seen[-1]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in seen[-1]["messages"][0]["content"]


def test_reply_cache_skips_the_provider(tmp_path):
    from storyforge.providers.llm.base import ChatReply, LLMProvider

    class Once(LLMProvider):
        name, model = "once", "m"

        def __init__(self):
            super().__init__(cache_dir=tmp_path)
            self.n = 0

        def chat(self, *a):
            self.n += 1
            return ChatReply(text=json.dumps(GOOD))

    a = Once()
    a.generate_json("continuity_log", "s", "u", "continuity")
    b = Once()
    b.generate_json("continuity_log", "s", "u", "continuity")
    assert (a.n, b.n) == (1, 0)
    b.generate_json("continuity_log", "s", "u", "continuity", variation=1)  # a fresh take bypasses the cache
    assert b.n == 1
