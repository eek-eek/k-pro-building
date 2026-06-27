"""Фабрика LLM-провайдера по настройкам окружения."""
from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from .anthropic import AnthropicProvider
from .base import LLMProvider
from .demo import DemoProvider
from .gemini import GeminiProvider
from .openai import OpenAIProvider


@lru_cache
def get_provider() -> LLMProvider:
    s = get_settings()
    provider = (s.llm_provider or "demo").lower()

    if provider == "gemini":
        return GeminiProvider(s.gemini_api_key, s.gemini_model, s.llm_use_search)
    if provider == "anthropic":
        return AnthropicProvider(s.anthropic_api_key, s.anthropic_model)
    if provider == "openai":
        return OpenAIProvider(s.openai_api_key, s.openai_model)
    return DemoProvider()
