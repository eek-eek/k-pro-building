"""LLM-провайдеры: единый интерфейс поверх Gemini / Anthropic / OpenAI / demo."""

from .factory import get_provider

__all__ = ["get_provider"]
