"""Фабрика провайдеров: сборка по явному имени."""
from __future__ import annotations

from app.llm.factory import build_named_provider, build_provider
from app.settings_service import EffectiveSettings


def _eff(provider="anthropic"):
    return EffectiveSettings(
        llm_provider=provider, gemini_api_key="g", anthropic_api_key="a",
        openai_api_key="o", gemini_model="gemini-2.5-flash",
        anthropic_model="claude-opus-4-8", openai_model="gpt-4o",
        llm_use_search=False,
    )


def test_build_named_provider_by_name():
    assert build_named_provider(_eff(), "openai").name == "openai"
    assert build_named_provider(_eff(), "anthropic").name == "anthropic"
    assert build_named_provider(_eff(), "gemini").name == "gemini"
    assert build_named_provider(_eff(), "demo").name == "demo"


def test_build_provider_delegates():
    assert build_provider(_eff("openai")).name == "openai"
