"""Demo-провайдер: ничего не вызывает, всегда «недоступен».

Используется в демо-режиме и при отсутствии ключей — расчёт уходит в
дефолтные нормативные коэффициенты.
"""
from __future__ import annotations

from .base import LLMProvider, LLMResult, LLMUnavailable


class DemoProvider(LLMProvider):
    name = "demo"
    available = False

    def complete(self, system, user, *, use_search=False, temperature=0.15) -> LLMResult:
        raise LLMUnavailable("Demo-режим: обращение к LLM отключено")
