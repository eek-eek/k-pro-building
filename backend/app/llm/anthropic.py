"""Anthropic Claude-провайдер (Messages API)."""
from __future__ import annotations

import httpx

from .base import LLMProvider, LLMResult, LLMUnavailable

ENDPOINT = "https://api.anthropic.com/v1/messages"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.available = bool(api_key)

    def complete(
        self,
        system: str,
        user: str,
        *,
        use_search: bool = False,
        temperature: float = 0.15,
    ) -> LLMResult:
        if not self.available:
            raise LLMUnavailable("ANTHROPIC_API_KEY не задан")

        # ВАЖНО: `temperature` НЕ передаём — новые модели Anthropic (Opus 4.x и
        # новее) его отвергают: "`temperature` is deprecated for this model".
        # Параметр оставлен в сигнатуре ради общего контракта провайдеров.
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            resp = httpx.post(
                ENDPOINT,
                json=body,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Anthropic сеть: {exc}") from exc

        if resp.status_code != 200:
            raise LLMUnavailable(f"Anthropic {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        blocks = payload.get("content") or []
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return LLMResult(text=text.strip(), sources=[], raw=payload)
