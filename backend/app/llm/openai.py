"""OpenAI-провайдер (Chat Completions API)."""
from __future__ import annotations

import httpx

from .base import LLMProvider, LLMResult, LLMUnavailable

ENDPOINT = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(LLMProvider):
    name = "openai"

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
            raise LLMUnavailable("OPENAI_API_KEY не задан")

        body = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            resp = httpx.post(
                ENDPOINT,
                json=body,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"OpenAI сеть: {exc}") from exc

        if resp.status_code != 200:
            raise LLMUnavailable(f"OpenAI {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        choices = payload.get("choices") or []
        text = choices[0]["message"]["content"].strip() if choices else ""
        return LLMResult(text=text, sources=[], raw=payload)
