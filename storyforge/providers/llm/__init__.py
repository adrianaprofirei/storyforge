"""LLM provider factory: Anthropic, OpenAI, or the offline demo provider."""

from __future__ import annotations

from storyforge.config import Settings
from storyforge.providers.llm.base import LLMError, LLMProvider, LLMUnavailable, extract_json

__all__ = ["get_llm", "LLMProvider", "LLMError", "LLMUnavailable", "extract_json"]


def get_llm(settings: Settings) -> LLMProvider:
    name = settings.resolved_llm_provider()
    if name == "anthropic":
        from storyforge.providers.llm.anthropic_llm import AnthropicLLM

        return AnthropicLLM(settings)
    if name == "openai":
        from storyforge.providers.llm.openai_llm import OpenAILLM

        return OpenAILLM(settings)
    from storyforge.providers.llm.demo import DemoLLM

    return DemoLLM(settings)
