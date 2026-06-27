"""Рекомендации — типовые позиции по нормам РК (СН РК/ГОСТ), часто не учтённые в
предварительной смете. Сервер сам досчитывает объём и стоимость по укрупнённым
показателям — по той же логике, что и `build_estimate` (ср. строку
«Подготовительные работы» = 1.5% от прямых затрат). Фронтенд только отображает
уже рассчитанные цифры и отправляет ключ выбранной позиции."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..schemas import BuildingInput, EstimateLine, EstimateResult

# Раздел, в который попадают добавленные рекомендации.
REC_SECTION = "Дополнительные позиции (рекомендации)"


def _direct(result: EstimateResult) -> float:
    return result.totals.direct or 0.0


def _footprint(inp: BuildingInput) -> float:
    return max(0.0, inp.building_length * inp.building_width)


# Функция стоимости: (BuildingInput, EstimateResult) → (объём, материал, работа, машины) за единицу.
CostFn = Callable[[BuildingInput, EstimateResult], "tuple[float, float, float, float]"]


@dataclass(frozen=True)
class Recommendation:
    key: str
    title: str
    unit: str
    norm: str
    cost: CostFn
    basis: str  # человекочитаемое описание базы расчёта
    keywords: tuple[str, ...] = ()  # если уже встречаются в смете — позицию не предлагаем
    floors_min: int = 0


# Каталог. Базы расчёта — укрупнённые показатели РК для ориентировочной (класс 5) сметы:
# инженерно-организационные позиции считаются процентом от прямых затрат (как «Подготовительные
# работы»), площадные/штучные — объём × индикативная цена за единицу.
RECOMMENDATIONS: list[Recommendation] = [
    Recommendation(
        key="geodesy",
        title="Геодезические разбивочные работы",
        unit="усл.",
        norm="СН РК 1.02-03",
        keywords=("геодез",),
        basis="0.3% от прямых затрат",
        cost=lambda inp, r: (1.0, 0.0, round(_direct(r) * 0.003), 0.0),
    ),
    Recommendation(
        key="temporary",
        title="Временные здания, дороги и площадки",
        unit="усл.",
        norm="СН РК 8.02-05",
        keywords=("временны", "подготов"),
        basis="2.0% от прямых затрат",
        cost=lambda inp, r: (1.0, 0.0, round(_direct(r) * 0.02), 0.0),
    ),
    Recommendation(
        key="vertical_planning",
        title="Вертикальная планировка территории",
        unit="м²",
        norm="СН РК 3.01-01",
        keywords=("вертикальн", "планировк", "благоустр"),
        basis="площадь застройки × 1.5; ~1 600 ₸/м²",
        cost=lambda inp, r: (round(_footprint(inp) * 1.5), 1000.0, 600.0, 0.0),
    ),
    Recommendation(
        key="elevators",
        title="Лифты и подъёмное оборудование",
        unit="шт",
        norm="СН РК 3.02-01",
        keywords=("лифт", "подъём"),
        floors_min=5,
        basis="1 лифт на ~9 этажей; ~13 млн ₸/шт с монтажом",
        cost=lambda inp, r: (max(1.0, round(inp.floors / 9)), 10_000_000.0, 3_000_000.0, 0.0),
    ),
    Recommendation(
        key="fire_safety",
        title="Пожарная сигнализация и пожаротушение",
        unit="м²",
        norm="СН РК 2.02-15",
        keywords=("пожарн", "сигнал", "пожаротуш"),
        basis="общая площадь × ~1 000 ₸/м²",
        cost=lambda inp, r: (round(inp.total_area), 600.0, 400.0, 0.0),
    ),
    Recommendation(
        key="lightning",
        title="Молниезащита и заземление",
        unit="усл.",
        norm="СО 153-34.21.122",
        keywords=("молниез", "заземл"),
        basis="0.4% от прямых затрат",
        cost=lambda inp, r: (1.0, 0.0, round(_direct(r) * 0.004), 0.0),
    ),
    Recommendation(
        key="commissioning",
        title="Пусконаладочные работы инженерных систем",
        unit="усл.",
        norm="СН РК 8.02-05",
        keywords=("пусконал", "наладк"),
        basis="1.0% от прямых затрат",
        cost=lambda inp, r: (1.0, 0.0, round(_direct(r) * 0.01), 0.0),
    ),
    Recommendation(
        key="supervision",
        title="Авторский и технический надзор",
        unit="усл.",
        norm="СН РК 1.02-03",
        keywords=("надзор", "авторск"),
        basis="1.5% от прямых затрат",
        cost=lambda inp, r: (1.0, 0.0, round(_direct(r) * 0.015), 0.0),
    ),
]

_BY_KEY: dict[str, Recommendation] = {r.key: r for r in RECOMMENDATIONS}


def _already_present(rec: Recommendation, result: EstimateResult) -> bool:
    hay = " | ".join(f"{ln.title} {ln.section}".lower() for ln in result.lines)
    return any(k in hay for k in rec.keywords)


def applicable_recommendations(
    inp: BuildingInput, result: EstimateResult
) -> list[dict]:
    """Список ещё не учтённых рекомендаций с уже рассчитанными объёмом и ценами."""
    items: list[dict] = []
    for rec in RECOMMENDATIONS:
        if rec.floors_min and inp.floors < rec.floors_min:
            continue
        if _already_present(rec, result):
            continue
        qty, material, labor, machine = rec.cost(inp, result)
        if qty <= 0:
            continue
        items.append({
            "key": rec.key,
            "title": rec.title,
            "unit": rec.unit,
            "norm": rec.norm,
            "basis": rec.basis,
            "quantity": qty,
            "material_price": material,
            "labor_price": labor,
            "machine_price": machine,
            "estimated_total": round(qty * (material + labor + machine)),
        })
    return items


def build_recommendation_line(
    key: str, inp: BuildingInput, result: EstimateResult
) -> EstimateLine:
    """Полностью заполненная строка сметы для рекомендации `key`. Объём и цены
    рассчитываются сервером; итог пересчитает `recompute_estimate` по той же формуле."""
    rec = _BY_KEY.get(key)
    if rec is None:
        raise KeyError(key)
    qty, material, labor, machine = rec.cost(inp, result)
    existing = sum(1 for ln in result.lines if ln.section == REC_SECTION)
    return EstimateLine(
        no=f"15.{existing + 1}",
        section=REC_SECTION,
        title=rec.title,
        norm=rec.norm,
        unit=rec.unit,
        quantity=qty,
        material_price=material,
        labor_price=labor,
        machine_price=machine,
        total=round(qty * (material + labor + machine)),
        needs_review=True,
        comment=f"добавлено из рекомендаций по укрупнённым показателям ({rec.basis}) — уточнить",
    )
