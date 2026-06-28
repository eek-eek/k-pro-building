"""Укрупнённые показатели РК: сид (предварительный) + резолв + якорь-сверка."""
from __future__ import annotations

from app.calc.generalized import (
    GENERALIZED_PRICE_LEVEL, seed_generalized_indicators,
)
from app.models import GeneralizedIndicator


def test_generalized_seeded(db):
    rows = db.query(GeneralizedIndicator).filter_by(price_level=GENERALIZED_PRICE_LEVEL).count()
    assert rows >= 3  # как минимум жилой дом / офис / склад


def test_generalized_seed_idempotent(db):
    before = db.query(GeneralizedIndicator).count()
    seed_generalized_indicators(db)
    after = db.query(GeneralizedIndicator).count()
    assert after == before  # повтор не плодит строк


def test_generalized_values_are_provisional(db):
    # Все засеянные показатели помечены как предварительные (нужен офиц. сборник).
    row = db.query(GeneralizedIndicator).filter_by(object_type="Жилой дом").first()
    assert row is not None
    assert row.needs_review is True
    assert row.value > 0
    assert row.unit == "м²"
