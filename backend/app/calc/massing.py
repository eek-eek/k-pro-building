"""Массинг здания (набор прямоугольных блоков): метрики для сметы + санитайз ИИ-вывода.

Геометрия считается из реальных блоков, поэтому смета остаётся точной даже для
произвольных форм (Г-образные, стилобат+башня, ступенчатые)."""
from __future__ import annotations

import math
from typing import Optional

from ..schemas import MassingBox

# Жёсткие границы (guardrails) — даже «допустимый» вывод ИИ проходит через них.
W_MAX = 500.0       # габарит блока в плане, м
FLOORS_MAX = 200    # этажей в блоке
BASE_MAX = 200      # этажей-смещение снизу
BOX_MAX = 16        # блоков в массинге
FH_MIN, FH_MAX = 2.0, 6.0   # разумная высота этажа, м


def _num(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _union_area(rects: list[tuple]) -> float:
    """Площадь объединения прямоугольников (x0,y0,x1,y1) — без двойного учёта
    перекрытий. Блоков мало (≤16), поэтому сетка по уникальным координатам дёшева."""
    xs = sorted({r[0] for r in rects} | {r[2] for r in rects})
    ys = sorted({r[1] for r in rects} | {r[3] for r in rects})
    area = 0.0
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            mx, my = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
            if any(r[0] <= mx <= r[2] and r[1] <= my <= r[3] for r in rects):
                area += (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
    return area


def massing_metrics(boxes: list[MassingBox], floor_height: float) -> dict:
    """Сводные метрики массинга для геометрии сметы.

    build_area — пятно застройки (объединение проекций ВСЕХ блоков на грунт — не
    обнуляется без блока base=0 и не двоит перекрытия); total_area — суммарная
    поэтажная; facade_area — наружные стены (консервативно, без вычета смежных);
    плюс объём, габариты bounding box и представительная этажность max(base+floors)."""
    fh = floor_height if floor_height and floor_height > 0 else 3.0
    if not boxes:
        return {"build_area": 0.0, "total_area": 0.0, "facade_area": 0.0,
                "building_volume": 0.0, "length": 0.0, "width": 0.0,
                "floors": 1, "total_height": 0.0}
    build_area = _union_area([(b.x, b.y, b.x + b.w, b.y + b.d) for b in boxes])
    total_area = sum(b.w * b.d * b.floors for b in boxes)
    building_volume = sum(b.w * b.d * b.floors * fh for b in boxes)
    facade_area = sum(2.0 * (b.w + b.d) * b.floors * fh for b in boxes)
    xs = [b.x for b in boxes] + [b.x + b.w for b in boxes]
    ys = [b.y for b in boxes] + [b.y + b.d for b in boxes]
    floors = max(b.base + b.floors for b in boxes)
    return {
        "build_area": build_area,
        "total_area": total_area,
        "facade_area": facade_area,
        "building_volume": building_volume,
        "length": max(xs) - min(xs),
        "width": max(ys) - min(ys),
        "floors": floors,
        "total_height": floors * fh,
    }


def sanitize_boxes(raw) -> tuple[list[MassingBox], list[str]]:
    """Привести сырой список блоков (от ИИ) к валидным MassingBox: отбраковать
    битые, зажать габариты/этажи, ограничить число. Вернуть (блоки, заметки)."""
    notes: list[str] = []
    if not isinstance(raw, list):
        return [], ["массинг не является списком блоков"]
    if len(raw) > BOX_MAX:
        notes.append(f"число блоков {len(raw)} больше {BOX_MAX} — лишние отброшены")
        raw = raw[:BOX_MAX]
    out: list[MassingBox] = []
    for i, r in enumerate(raw):
        if not isinstance(r, dict):
            notes.append(f"блок {i}: не объект — пропущен")
            continue
        w, d = _num(r.get("w")), _num(r.get("d"))
        if w is None or d is None or w <= 0 or d <= 0:
            notes.append(f"блок {i}: некорректные габариты — пропущен")
            continue
        cw, cd = min(max(w, 1.0), W_MAX), min(max(d, 1.0), W_MAX)
        if cw != w or cd != d:
            notes.append(f"блок {i}: габариты зажаты в [1, {W_MAX:g}] м")
        fl_raw = _num(r.get("floors", 1))
        fl = min(max(int(round(fl_raw)) if fl_raw is not None else 1, 1), FLOORS_MAX)
        if fl_raw is None or fl_raw < 1 or fl_raw != round(fl_raw):
            notes.append(f"блок {i}: этажность приведена к целому в [1, {FLOORS_MAX}]")
        ba_raw = _num(r.get("base", 0)) or 0.0
        ba = min(max(int(round(ba_raw)), 0), BASE_MAX)
        out.append(MassingBox(x=_num(r.get("x", 0)) or 0.0, y=_num(r.get("y", 0)) or 0.0,
                              w=cw, d=cd, floors=fl, base=ba))
    if not out:
        notes.append("нет валидных блоков")
        return out, notes
    # Опустить здание на грунт: если нижний ярус приподнят (нет блока base=0) —
    # сдвинуть все блоки вниз, иначе пятно/высота посчитаются неверно.
    min_base = min(b.base for b in out)
    if min_base > 0:
        for b in out:
            b.base -= min_base
        notes.append("здание опущено на грунт (нижний ярус был приподнят)")
    return out, notes
