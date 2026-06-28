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


def test_resolve_indicator_for_object(db):
    from app.calc.generalized import resolve_generalized_indicator
    from app.schemas import BuildingInput
    ind = resolve_generalized_indicator(db, BuildingInput(object_type="Жилой дом"))
    assert ind is not None and ind.object_type == "Жилой дом"
    none = resolve_generalized_indicator(db, BuildingInput(object_type="НесуществующийТип"))
    assert none is None


def test_compute_cost_anchor(db):
    from app.calc.generalized import compute_cost_anchor
    from app.schemas import BuildingInput
    inp = BuildingInput(object_type="Жилой дом", total_area=1000.0)  # 1000 м²
    anchor = compute_cost_anchor(db, inp, resource_grand=300_000_000.0)
    assert anchor is not None
    assert anchor.indicator_per_unit > 0
    assert anchor.value == round(1000.0 * anchor.indicator_per_unit)  # площадь × показатель
    assert anchor.provisional is True
    assert anchor.deviation_pct == round((300_000_000 - anchor.value) / anchor.value * 100, 1)


def test_compute_cost_anchor_none_when_no_indicator(db):
    from app.calc.generalized import compute_cost_anchor
    from app.schemas import BuildingInput
    anchor = compute_cost_anchor(db, BuildingInput(object_type="НетТакого"), 1.0)
    assert anchor is None
