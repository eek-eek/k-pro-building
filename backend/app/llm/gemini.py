"""Gemini-провайдер (generativelanguage API) с google_search grounding."""
from __future__ import annotations

import httpx

from .base import LLMProvider, LLMResult, LLMUnavailable

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, use_search_default: bool = True):
        self.api_key = api_key
        self.model = model
        self.use_search_default = use_search_default
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
            raise LLMUnavailable("GEMINI_API_KEY не задан")

        body: dict = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature},
        }
        if use_search:
            body["tools"] = [{"google_search": {}}]

        url = ENDPOINT.format(model=self.model)
        try:
            resp = httpx.post(
                url,
                params={"key": self.api_key},
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=120.0,
            )
        except httpx.HTTPError as exc:  # сетевые проблемы
            raise LLMUnavailable(f"Gemini сеть: {exc}") from exc

        if resp.status_code != 200:
            raise LLMUnavailable(f"Gemini {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        return LLMResult(
            text=_extract_text(payload),
            sources=_extract_sources(payload),
            raw=payload,
        )


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "\n".join(p.get("text", "") for p in parts).strip()


def _extract_sources(payload: dict) -> list[dict]:
    candidates = payload.get("candidates") or []
    if not candidates:
        return []
    grounding = candidates[0].get("groundingMetadata") or {}
    sources: list[dict] = []
    for chunk in grounding.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        if web.get("uri"):
            sources.append({"title": web.get("title", "source"), "url": web["uri"]})
    return sources
