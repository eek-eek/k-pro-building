"""Укрупнённые показатели стоимости РК (НДЦС/УСН РК): сид, резолв, якорь-сверка.

ВНИМАНИЕ: засеянные значения — ПРЕДВАРИТЕЛЬНЫЕ ориентиры (needs_review=True),
подлежат замене значениями из официального сборника РК (пайплайн импорта, План 1C).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GeneralizedIndicator
from ..schemas import BuildingInput, CostAnchor

GENERALIZED_PRICE_LEVEL = "НДЦС-2025-предварительно"

# Предварительные укрупнённые показатели (₸/м² общей площади), национально (KZ).
# ЗАГЛУШКА: заменить официальными значениями НДЦС/УСН РК (План 1C).
_SEED: list[dict] = [
    {"object_type": "Жилой дом", "value": 320000.0},
    {"object_type": "Офис", "value": 360000.0},
    {"object_type": "Коммерческое помещение", "value": 340000.0},
    {"object_type": "Склад", "value": 180000.0},
    {"object_type": "Производственный объект", "value": 260000.0},
]
_SEED_NOTE = "Предварительный ориентир — заменить значением из официального сборника НДЦС/УСН РК"
_SEED_SOURCE = "НДЦС РК 8.02-01 (предв.)"


def seed_generalized_indicators(db: Session, region: str = "KZ") -> None:
    """Идемпотентно засеять предварительные укрупнённые показатели."""
    for row in _SEED:
        exists = db.scalar(
            select(GeneralizedIndicator).where(
                GeneralizedIndicator.object_type == row["object_type"],
                GeneralizedIndicator.region == region,
                GeneralizedIndicator.price_level == GENERALIZED_PRICE_LEVEL,
            )
        )
        if exists:
            continue
        db.add(GeneralizedIndicator(
            object_type=row["object_type"], region=region, value=row["value"],
            unit="м²", price_level=GENERALIZED_PRICE_LEVEL,
            source_code=_SEED_SOURCE, note=_SEED_NOTE, needs_review=True,
        ))
    db.commit()


def resolve_generalized_indicator(
    db: Session, inp: BuildingInput
) -> Optional[GeneralizedIndicator]:
    """Найти укрупнённый показатель под объект: регион города → KZ."""
    region = inp.city.split("/")[0].strip() or "KZ"
    for reg in dict.fromkeys((region, "KZ")):  # без повторного запроса при пустом регионе
        row = db.scalars(
            select(GeneralizedIndicator)
            .where(
                GeneralizedIndicator.object_type == inp.object_type,
                GeneralizedIndicator.region == reg,
            )
            # подтверждённые (needs_review=False) раньше предварительных; .first()
            # вместо .scalar() — устойчиво к нескольким уровням цен (План 1C).
            .order_by(GeneralizedIndicator.needs_review)
        ).first()
        if row is not None:
            return row
    return None


def compute_cost_anchor(
    db: Session, inp: BuildingInput, resource_grand: float
) -> Optional[CostAnchor]:
    """Укрупнённый ориентир + отклонение ресурсной сметы (None, если показателя нет)."""
    ind = resolve_generalized_indicator(db, inp)
    if ind is None:
        return None
    area = inp.total_area or 0.0
    value = round(area * ind.value)
    deviation = round((resource_grand - value) / value * 100, 1) if value else 0.0
    return CostAnchor(
        value=value, indicator_per_unit=ind.value, unit=ind.unit, area=area,
        source_code=ind.source_code, source_url=ind.source_url, note=ind.note,
        provisional=ind.needs_review, resource_grand=round(resource_grand),
        deviation_pct=deviation,
    )
