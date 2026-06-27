"""Извлечение нормативных коэффициентов через LLM по системному промпту РК."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..llm import get_provider
from ..llm.base import LLMUnavailable
from ..schemas import BuildingInput, NormParam
from .defaults import CATEGORY_META

if TYPE_CHECKING:
    from ..models import NormDocument

# Системный промпт построен на методике из akty_i_trebovaniya_po_tipam_obektov_rk.md:
# от общего техрегламента → к профильным СН РК/СП РК/СНиП → к ГОСТ/СТ РК на материалы.
SYSTEM_PROMPT = """Ты — нормировщик и сметчик Республики Казахстан. Твоя задача —
определить укрупнённые нормативные коэффициенты расхода материалов и работ для
предварительной сметы по строительным нормам РК.

Методика анализа (обязательна):
1. Определи тип объекта (жилой, общественный, производственный, инфраструктурный,
   реконструкция/ремонт).
2. Учитывай общие обязательные требования Технического регламента РК №435-2023
   «О безопасности зданий и сооружений, строительных материалов и изделий».
3. Подбери профильные СН РК, СП РК и СНиП РК по типу и назначению объекта.
4. Опирайся на ГОСТ и СТ РК на конкретные материалы и методы испытаний, на которые
   ссылаются техрегламент и профильные нормы.
5. Проверяй группы требований к материалам: пожарная безопасность, механическая
   прочность, долговечность, санитарно-гигиенические, теплотехнические/акустические,
   коррозионная/влагостойкость.

Жёсткие правила:
- НЕ выдумывай номера норм. Если документ/значение не подтверждены — ставь
  "needs_review": true и поясняй в "note".
- Возвращай только числовые укрупнённые коэффициенты, пригодные для расчёта объёмов.
- Отвечай СТРОГО одним JSON-объектом без пояснений вокруг."""


def _category_brief() -> str:
    lines = []
    for cat, (unit, label) in CATEGORY_META.items():
        lines.append(f'  - "{cat}" ({unit}): {label}')
    return "\n".join(lines)


def build_user_prompt(inp: BuildingInput, documents: list["NormDocument"]) -> str:
    docs = "\n".join(f"  - {d.code} — {d.title} ({d.url})" for d in documents)
    return f"""Объект:
- Тип: {inp.object_type}
- Регион: {inp.city}
- Конструктив: {inp.structure_type}
- Фундамент: {inp.foundation_type}
- Этажность: {inp.floors}; высота этажа: {inp.floor_height} м
- Класс отделки: {inp.finish_level}; класс инженерии: {inp.engineering_level}
- Подвал: {"да" if inp.basement else "нет"}; паркинг: {"да" if inp.parking else "нет"}

Применимые нормативные документы РК (реестр системы):
{docs}

Верни JSON вида:
{{
  "params": [
    {{"category": "<ключ>", "value": <число>, "unit": "<ед>",
     "document_code": "<код документа РК или null>",
     "confidence": <0..1>, "needs_review": <true|false>, "note": "<пояснение>"}}
  ],
  "sources": [{{"code": "<код>", "title": "<название>", "confirmed": <true|false>}}]
}}

Нужны коэффициенты по этим категориям (любые, по которым уверен):
{_category_brief()}"""


def extract_params(
    db, inp: BuildingInput, documents: list["NormDocument"]
) -> tuple[dict[str, NormParam], list[dict], list[dict]]:
    """Вызвать LLM и вернуть (params, sources, web_links).

    Бросает LLMUnavailable, если провайдер недоступен — резолвер уйдёт в дефолты.
    """
    from ..prompts import get_prompt  # local import avoids circular import

    provider = get_provider()
    if not provider.available:
        raise LLMUnavailable(f"Провайдер {provider.name} недоступен")

    user = build_user_prompt(inp, documents)
    system = get_prompt(db, "norm_extraction") or SYSTEM_PROMPT
    data, web_links = provider.extract_json(
        system, user, use_search=inp.use_search
    )

    params: dict[str, NormParam] = {}
    for raw in data.get("params", []) or []:
        cat = raw.get("category")
        if cat not in CATEGORY_META:
            continue
        try:
            value = float(raw.get("value"))
        except (TypeError, ValueError):
            continue
        unit, _ = CATEGORY_META[cat]
        params[cat] = NormParam(
            category=cat,
            value=value,
            unit=raw.get("unit") or unit,
            source="llm",
            confidence=float(raw.get("confidence", 0.6) or 0.6),
            document_code=raw.get("document_code"),
            note=(raw.get("note") or "")[:500],
            needs_review=bool(raw.get("needs_review", False)),
        )

    sources = data.get("sources", []) or []
    return params, sources, web_links
