"""ИИ-генерация формы здания (массинг из блоков) с нормоконтролем РК.

Модель интерпретирует описание, оценивает по нормам РК (СН РК/СНиП РК) и физике,
возвращает status/message/boxes. Сервер дополнительно зажимает габариты и проверяет
стройность — это ИИ-оценка, не сертифицированный расчёт."""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from ..llm import get_provider
from ..llm.base import LLMUnavailable
from ..schemas import BuildingForm
from .massing import FH_MIN, FH_MAX, FLOORS_MAX, W_MAX, BOX_MAX, _num, sanitize_boxes

SLENDERNESS_MAX = 15.0  # высота / меньшую сторону застройки — мягкий предел устойчивости

SYSTEM = f"""Ты инженер-архитектор. По описанию построй ОБЪЁМНУЮ форму здания как набор
прямоугольных блоков (массинг) и проверь её на соответствие нормам РК и физике.

Система координат — план в метрах: x,y — угол блока, w — ширина (вдоль X), d — глубина
(вдоль Y), floors — этажей в блоке, base — на сколько этажей блок приподнят снизу
(башня на стилобате: base = этажность стилобата). Один прямоугольный дом — один блок.
Г-образный — два блока встык. Стилобат+башня — широкий блок base=0 и узкий блок выше.

НОРМОКОНТРОЛЬ. Оцени запрос по нормам РК (СН РК / СНиП РК: противопожарные разрывы и
предельная длина здания без разрывов, конструктивная устойчивость — соотношение высоты
к меньшей стороне основания, предельная этажность для конструктива) и физической
реализуемости. Действуй так:
- реализуемо как запрошено → status="ok";
- противоречит нормам/физике, но есть близкий допустимый вариант → status="adjusted",
  построй ближайшую ДОПУСТИМУЮ форму и в message объясни, что и почему изменил;
- принципиально нереализуемо → status="rejected", boxes=[], в message объясни почему.

Ограничения: не более {BOX_MAX} блоков; габариты блока 1..{int(W_MAX)} м; floors 1..{FLOORS_MAX};
base ≥ 0. Базовые габариты сметы используй как ориентир, если описание их не переопределяет.

Верни СТРОГО JSON без пояснений вокруг:
{{"status":"ok|adjusted|rejected","message":"кратко по-русски","floor_height":3.0,
"boxes":[{{"x":0,"y":0,"w":40,"d":30,"floors":3,"base":0}}]}}"""


def _user(description: str, base: dict) -> str:
    b = base or {}
    parts = [f"Описание формы: {description or '(не задано)'}"]
    hints = []
    for k, label in (("object_type", "тип"), ("building_length", "длина участка-габарита, м"),
                     ("building_width", "ширина, м"), ("floors", "этажей"),
                     ("floor_height", "высота этажа, м")):
        if b.get(k):
            hints.append(f"{label}={b[k]}")
    if hints:
        parts.append("Базовые параметры сметы: " + ", ".join(hints))
    return "\n".join(parts)


def _demo_box(base: dict) -> BuildingForm:
    """Фолбэк без ИИ: прямоугольная форма из габаритов сметы (описание не интерпретируется)."""
    b = base or {}
    w = _num(b.get("building_length")) or 30.0
    d = _num(b.get("building_width")) or 20.0
    fl = int(_num(b.get("floors")) or 5)
    fh = min(max(_num(b.get("floor_height")) or 3.0, FH_MIN), FH_MAX)
    boxes, _notes = sanitize_boxes([{"x": 0, "y": 0, "w": w, "d": d, "floors": fl, "base": 0}])
    return BuildingForm(
        status="ok", floor_height=fh, boxes=boxes,
        message="ИИ недоступен (демо-режим или не задан ключ): построена прямоугольная "
                "форма из габаритов сметы, описание не интерпретировалось.")


def _slenderness_note(boxes, floor_height: float) -> str | None:
    """Мягкая проверка устойчивости: высота / меньшую сторону застройки."""
    ground = [b for b in boxes if b.base == 0] or boxes
    min_side = min((min(b.w, b.d) for b in ground), default=0.0)
    height = max((b.base + b.floors for b in boxes), default=0) * (floor_height or 3.0)
    if min_side > 0 and height / min_side > SLENDERNESS_MAX:
        return (f"конструктивная устойчивость под вопросом — высота ({height:.0f} м) к "
                f"меньшей стороне основания ({min_side:.0f} м) превышает рекомендуемое "
                f"~{SLENDERNESS_MAX:g}:1")
    return None


def generate_form(db: Session, description: str, base: dict) -> BuildingForm:
    provider = get_provider()
    fh = min(max(_num((base or {}).get("floor_height")) or 3.0, FH_MIN), FH_MAX)
    try:
        data, _sources = provider.extract_json(SYSTEM, _user(description, base), use_search=False)
    except LLMUnavailable:
        return _demo_box(base)

    status = str(data.get("status") or "ok").strip().lower()
    message = str(data.get("message") or "").strip()
    fh = min(max(_num(data.get("floor_height")) or fh, FH_MIN), FH_MAX)

    if status == "rejected":
        return BuildingForm(status="rejected", floor_height=fh, boxes=[],
                            message=message or "Запрошенная форма нереализуема.")

    boxes, notes = sanitize_boxes(data.get("boxes"))
    if not boxes:
        return BuildingForm(status="rejected", floor_height=fh, boxes=[],
                            message=(message + " " if message else "") + "ИИ не вернул валидную геометрию.")

    extra = list(notes)
    slim = _slenderness_note(boxes, fh)
    if slim:
        extra.append(slim)
    if extra and status == "ok":
        status = "adjusted"  # серверная правка/замечание → форма уже не «как запрошено»
    if extra:
        message = (message + " " if message else "") + "Серверная проверка: " + "; ".join(extra) + "."
    if status not in ("ok", "adjusted"):
        status = "adjusted"
    return BuildingForm(status=status, message=message, floor_height=fh, boxes=boxes)
