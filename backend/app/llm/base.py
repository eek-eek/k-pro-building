"""Базовый интерфейс LLM-провайдера и утилиты разбора ответа."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


class LLMUnavailable(RuntimeError):
    """LLM не настроен или недоступен — вызывающий код уходит в дефолты."""


@dataclass
class LLMResult:
    text: str
    sources: list[dict] = field(default_factory=list)  # web-grounding ссылки
    raw: dict | None = None


class LLMProvider:
    """Контракт провайдера. Реализации переопределяют `complete`."""

    name: str = "base"
    available: bool = False

    def complete(
        self,
        system: str,
        user: str,
        *,
        use_search: bool = False,
        temperature: float = 0.15,
    ) -> LLMResult:
        raise NotImplementedError

    # ── общие помощники ───────────────────────────────────────────────
    def extract_json(
        self,
        system: str,
        user: str,
        *,
        use_search: bool = False,
    ) -> tuple[dict, list[dict]]:
        """Вызвать модель и вытащить первый JSON-объект из ответа."""
        result = self.complete(system, user, use_search=use_search)
        return parse_json_block(result.text), result.sources


def parse_json_block(text: str) -> dict:
    """Достать JSON-объект из произвольного текста модели."""
    if not text:
        return {}
    # ```json ... ``` блок
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        # первый '{' до парного '}'
        start = text.find("{")
        end = text.rfind("}")
        candidate = text[start : end + 1] if start != -1 and end > start else ""
    if not candidate:
        return {}
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # último: убрать висячие запятые
        cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}
