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


def test_build_estimate_attaches_anchor(db):
    from app.calc import build_estimate
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput
    inp = BuildingInput(demo_mode=True, use_search=False, object_type="Жилой дом")
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    assert r.cost_anchor is not None
    assert r.cost_anchor.value > 0
    assert r.cost_anchor.resource_grand == round(r.totals.grand_total)
    assert r.cost_anchor.provisional is True


def test_recompute_carries_anchor(db):
    from app.calc import build_estimate, recompute_estimate
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput
    inp = BuildingInput(demo_mode=True, use_search=False, object_type="Жилой дом")
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    assert r.cost_anchor is not None
    r2 = recompute_estimate(r, [ln.model_copy(deep=True) for ln in r.lines], inp)
    assert r2.cost_anchor is not None
    assert r2.cost_anchor.value == r.cost_anchor.value  # показатель не меняется
    assert r2.cost_anchor.resource_grand == round(r2.totals.grand_total)


def test_anchor_deviation_warning_present(db):
    from app.calc import build_estimate
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput
    inp = BuildingInput(demo_mode=True, use_search=False, object_type="Жилой дом")
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    assert abs(r.cost_anchor.deviation_pct) > 25  # демо-кейс даёт ~-65%
    hits = [w for w in r.warnings if "укрупнённого ориентира РК" in w]
    assert len(hits) == 1
    assert f"{r.cost_anchor.deviation_pct:+.0f}%" in hits[0]
    assert "предварительный показатель" in hits[0]  # provisional=True


def test_anchor_no_warning_within_threshold(db):
    # отклонение ≤25% → нет предупреждения
    from app.calc.generalized import compute_cost_anchor
    from app.schemas import BuildingInput
    inp = BuildingInput(object_type="Жилой дом", total_area=1000.0)
    anchor = compute_cost_anchor(db, inp, resource_grand=1000.0 * anchor_value(db))
    assert abs(anchor.deviation_pct) <= 25


def anchor_value(db):
    from app.calc.generalized import resolve_generalized_indicator
    from app.schemas import BuildingInput
    return resolve_generalized_indicator(db, BuildingInput(object_type="Жилой дом")).value


def test_build_estimate_no_anchor_for_unknown_type(db):
    from app.calc import build_estimate
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput
    inp = BuildingInput(object_type="Автомойка", demo_mode=True, use_search=False)
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    assert r.cost_anchor is None  # тип без показателя
    assert not any("укрупнённого ориентира" in w for w in r.warnings)


def test_recompute_anchor_none_stays_none(db):
    from app.calc import build_estimate, recompute_estimate
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput
    inp = BuildingInput(object_type="Автомойка", demo_mode=True, use_search=False)
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    assert r.cost_anchor is None
    r2 = recompute_estimate(r, [ln.model_copy(deep=True) for ln in r.lines], inp)
    assert r2.cost_anchor is None
