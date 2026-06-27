"""Фабрика LLM-провайдера из эффективных настроек (env + БД)."""
from __future__ import annotations

from ..database import SessionLocal
from .anthropic import AnthropicProvider
from .base import LLMProvider
from .demo import DemoProvider
from .gemini import GeminiProvider
from .openai import OpenAIProvider


def build_provider(eff) -> LLMProvider:
    provider = (eff.llm_provider or "demo").lower()
    if provider == "gemini":
        return GeminiProvider(eff.gemini_api_key, eff.gemini_model, eff.llm_use_search)
    if provider == "anthropic":
        return AnthropicProvider(eff.anthropic_api_key, eff.anthropic_model)
    if provider == "openai":
        return OpenAIProvider(eff.openai_api_key, eff.openai_model)
    return DemoProvider()


def get_provider() -> LLMProvider:
    """Build a provider from current effective settings (reads DB each call → hot reload)."""
    from ..settings_service import get_effective_settings
    with SessionLocal() as db:
        eff = get_effective_settings(db)
    return build_provider(eff)
