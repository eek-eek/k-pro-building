"""Укрупнённые показатели стоимости РК (НДЦС/УСН РК): сид, резолв, якорь-сверка.

ВНИМАНИЕ: засеянные значения — ПРЕДВАРИТЕЛЬНЫЕ ориентиры (needs_review=True),
подлежат замене значениями из официального сборника РК (пайплайн импорта, План 1C).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GeneralizedIndicator

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
