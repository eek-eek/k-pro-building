"""Извлечение нормативных коэффициентов через LLM по системному промпту РК."""
from __future__ import annotations

import json
import math
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
2. Высший рамочный уровень отрасли — Строительный кодекс РК №253-VIII (введён в
   действие с 01.07.2026; заменил Закон №242 «Об архитектурной, градостроительной
   и строительной деятельности»). Общие обязательные требования безопасности —
   Технический регламент РК №435-2023 «О безопасности зданий и сооружений,
   строительных материалов и изделий».
3. Подбери профильные СН РК, СП РК и СНиП РК и подзаконные акты к Кодексу (правила
   АГСК-каталогов, градостроительных проектов, организации застройки) по типу и
   назначению объекта.
4. Опирайся на ГОСТ и СТ РК на конкретные материалы и методы испытаний, на которые
   ссылаются техрегламент и профильные нормы.
5. Проверяй группы требований к материалам: пожарная безопасность, механическая
   прочность, долговечность, санитарно-гигиенические, теплотехнические/акустические,
   коррозионная/влагостойкость; в сейсмоопасных регионах — сейсмическая безопасность
   по Строительному кодексу РК: выбор площадки и сейсмомикрозонирование (ст. 34);
   на селе-/оползнеопасных участках — не выше 3 этажей, в г. Алматы — запрет новой
   застройки в жилой/общественной/промышленной зоне (ст. 78); сейсмоизоляция и
   паспортизация (ст. 126–129); СП РК 2.03-30.

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

    params = _parse_params(data)
    sources = data.get("sources", []) or []
    return params, sources, web_links


def _parse_params(data: dict) -> dict[str, NormParam]:
    """Разобрать data['params'] в нормы. Отбрасывает неизвестные категории и
    невалидные значения (нечисловые / не конечные / отрицательные). Устойчиво к
    мусору от недоверенной модели (не-dict, нечисловой confidence) — не бросает."""
    if not isinstance(data, dict):
        return {}
    params: dict[str, NormParam] = {}
    for raw in data.get("params", []) or []:
        if not isinstance(raw, dict):
            continue
        cat = raw.get("category")
        if cat not in CATEGORY_META:
            continue
        try:
            value = float(raw.get("value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        try:
            conf = float(raw.get("confidence", 0.6))
        except (TypeError, ValueError):
            conf = 0.6
        if not math.isfinite(conf):
            conf = 0.6
        conf = min(max(conf, 0.0), 1.0)
        unit, _ = CATEGORY_META[cat]
        params[cat] = NormParam(
            category=cat,
            value=value,
            unit=raw.get("unit") or unit,
            source="llm",
            confidence=conf,
            document_code=raw.get("document_code"),
            note=(raw.get("note") or "")[:500],
            needs_review=bool(raw.get("needs_review", False)),
        )
    return params


# ── Ансамбль: независимая кросс-проверка норм вторым провайдером ──
REL_TOL = 0.15      # порог относительного расхождения значений
ABS_FLOOR = 1e-3    # пол знаменателя (корректное сравнение при значениях ~0)
CONF_BONUS = 0.15   # прибавка к уверенности при согласии
NOTE_MAX = 500      # лимит длины ноты


def _cap_note(s: str) -> str:
    return s[:NOTE_MAX]


def _pct(rel: float) -> str:
    return f"{min(rel, 9.99):.0%}"


def cross_check_params(db, inp: BuildingInput, documents, primary_params):
    """Независимо извлечь нормы проверяющим провайдером и сверить с primary_params.

    Аннотирует primary_params (confidence/needs_review/note) на месте и возвращает
    (primary_params, CrossCheck). Мягкая деградация на всех путях отказа.
    """
    from ..schemas import CrossCheck
    from ..settings_service import get_effective_settings
    from ..llm.factory import build_named_provider
    from ..prompts import get_prompt

    eff = get_effective_settings(db)
    if not primary_params:
        return primary_params, CrossCheck(enabled=eff.cross_check_enabled, ran=False,
                                          reason="основное LLM-извлечение пусто")
    if not eff.cross_check_enabled:
        return primary_params, CrossCheck(enabled=False)
    if (eff.cross_check_provider or "").lower() == (eff.llm_provider or "").lower():
        return primary_params, CrossCheck(enabled=True, ran=False,
                                          reason="проверяющий совпадает с основным")
    verifier = build_named_provider(eff, eff.cross_check_provider)
    if not verifier.available:
        return primary_params, CrossCheck(enabled=True, ran=False,
                                          reason="проверяющий недоступен (нет ключа)")

    user = build_user_prompt(inp, documents)
    system = get_prompt(db, "norm_extraction") or SYSTEM_PROMPT
    try:
        # тот же режим web-поиска, что у основного вызова — равные условия сравнения
        data, _ = verifier.extract_json(system, user, use_search=inp.use_search)
    except LLMUnavailable:
        return primary_params, CrossCheck(enabled=True, ran=False,
                                          reason="ошибка проверяющего")
    verifier_params = _parse_params(data)
    if not verifier_params:
        return primary_params, CrossCheck(enabled=True, ran=False,
                                          reason="проверяющий вернул нечитаемый ответ")

    agreed = disputed = missing = 0
    extra_keys = [c for c in verifier_params if c not in primary_params]
    for cat, p in primary_params.items():
        v = verifier_params.get(cat)
        if v is None:
            missing += 1
            p.note = _cap_note(p.note + " · вторая модель не дала значение")
            continue
        if p.unit and v.unit and p.unit != v.unit:
            p.needs_review = True
            p.note = _cap_note(p.note + f" · ⚠ единицы расходятся: {p.unit} vs {v.unit}")
            disputed += 1
            continue
        denom = max(abs(p.value), abs(v.value), ABS_FLOOR)
        rel = abs(p.value - v.value) / denom
        if rel <= REL_TOL:
            p.confidence = min(1.0, p.confidence + CONF_BONUS)
            p.note = _cap_note(p.note + f" · ✓ подтверждено {verifier.name}")
            agreed += 1
        else:
            p.needs_review = True
            p.note = _cap_note(
                p.note + f" · ⚠ расхождение с {verifier.name}: {p.value} vs {v.value} ({_pct(rel)})"
            )
            disputed += 1
    return primary_params, CrossCheck(
        enabled=True, ran=True, verifier=eff.cross_check_provider,
        agreed=agreed, disputed=disputed, missing=missing,
        extra=len(extra_keys), extra_keys=extra_keys[:10],
    )
