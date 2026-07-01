"""Ставки труда из справочника SADI (`LaborTariff`) в расчёте сметы.

Замена цены labor-ресурсов сметной тарифной ставкой (₸/чел-ч) по региону и
разряду × индекс (2016 → год расчёта). Шкалы сверены: SADI-2016 ≈ рыночный
сид-2026 (₸/чел-ч), поэтому дефолтный индекс 1.0 не даёт абсурда. ИТР сюда не
входят — их затраты покрываются накладными (`overhead_pct`)."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LaborTariff

WORKER_KIND = "рабочие-строители/машинисты"

# Город сметы → регион тарифной таблицы SADI (наши города: Алматы/Астана/Шымкент).
CITY_TO_REGION = {
    "Алматы": "Алматы",
    "Астана": "Астана",
    "Нур-Султан": "Астана",
    "Шымкент": "Южно-Казахстанской области",
}
DEFAULT_RANK = "4"  # если разряд не распознан в названии ресурса — берём средний


def region_for_city(city: str) -> str | None:
    """Регион тарифной таблицы для города сметы (или None, если сопоставления нет)."""
    city = (city or "").strip()
    if city in CITY_TO_REGION:
        return CITY_TO_REGION[city]
    return city if city.endswith("области") else None  # уже название области


def rank_from_name(name: str) -> str:
    """Разряд из названия ресурса («Бетонщик 4 р.» → '4'); иначе средний."""
    m = re.search(r"(\d+)\s*р", name or "")
    return m.group(1) if m else DEFAULT_RANK


def worker_rates(db: Session, region: str) -> dict[str, float]:
    """{целый разряд '1'..'8' → ставка ₸/чел-ч} для региона (только рабочие/машинисты)."""
    rows = db.scalars(
        select(LaborTariff).where(
            LaborTariff.region == region, LaborTariff.kind == WORKER_KIND
        )
    ).all()
    out: dict[str, float] = {}
    for r in rows:
        if r.category.endswith(".00"):        # ровный разряд N.00
            out[r.category.split(".")[0]] = r.rate
    return out


def apply_labor_tariffs(resources, rates: dict[str, float], index: float,
                        today_iso: str) -> bool:
    """Заменить цену labor-ресурсов ставкой тарифа (₸/чел-ч × index). Мутирует
    `ResourceLine` (price/source/updated_at — штамп «сегодня»: индекс и есть
    индексация, чтобы инфляция не задвоила). True, если что-то применили."""
    if not rates:
        return False
    applied = False
    for res in resources:
        if res.kind != "labor":
            continue
        rate = rates.get(rank_from_name(res.name)) or rates.get(DEFAULT_RANK)
        if not rate:
            continue
        res.price = round(rate * index)
        res.source = "sadi-tariff"
        res.updated_at = today_iso
        applied = True
    return applied
