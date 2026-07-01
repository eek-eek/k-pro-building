"""Подключение тарифных ставок труда SADI к расчёту сметы."""
from __future__ import annotations

from app.calc import build_estimate
from app.calc.labor_tariff import (
    apply_labor_tariffs, rank_from_name, region_for_city, worker_rates,
)
from app.norms import resolve_norm_profile
from app.schemas import BuildingInput, ResourceLine
from app.settings_service import save_settings


def _est(db, city="Астана"):
    inp = BuildingInput(demo_mode=True, use_search=False, city=city,
                        building_length=20, building_width=15, floors=5)
    return build_estimate(db, inp, resolve_norm_profile(db, inp))


def _excavator_labor(res):
    for ln in res.lines:
        for r in (ln.resources or []):
            if r.kind == "labor" and "экскаватор" in r.name.lower():
                return r
    return None


def test_region_for_city():
    assert region_for_city("Астана") == "Астана"
    assert region_for_city("Шымкент") == "Южно-Казахстанской области"
    assert region_for_city("Актюбинской области") == "Актюбинской области"
    assert region_for_city("Мадрид") is None


def test_rank_from_name():
    assert rank_from_name("Машинист экскаватора 6 р.") == "6"
    assert rank_from_name("Бетонщик 4 р.") == "4"
    assert rank_from_name("Монтажник светопрозрачных конструкций") == "4"  # дефолт


def test_worker_rates_loaded(db):
    rates = worker_rates(db, "Астана")
    assert rates.get("6") and rates["6"] > 0
    # выше разряд — выше ставка
    assert rates["6"] > rates["2"]


def test_apply_labor_tariffs_mutates_only_labor():
    res = [
        ResourceLine(code="m", name="Бетон", kind="material", unit="м³", consumption=1, price=30000),
        ResourceLine(code="l", name="Бетонщик 4 р.", kind="labor", unit="чел-ч", consumption=2, price=3500),
    ]
    applied = apply_labor_tariffs(res, {"4": 3346.0}, 1.0, "2026-07-01")
    assert applied is True
    assert res[0].price == 30000            # материал не тронут
    assert res[1].price == 3346 and res[1].source == "sadi-tariff"


def test_index_scales_rate():
    res = [ResourceLine(code="l", name="Бетонщик 4 р.", kind="labor", unit="чел-ч", consumption=1, price=1000)]
    apply_labor_tariffs(res, {"4": 3000.0}, 1.2, "2026-07-01")
    assert res[0].price == round(3000 * 1.2)


def test_estimate_uses_tariff_and_differs_by_region(db):
    save_settings(db, {"labor_tariff_enabled": True, "labor_tariff_index": 1.0})
    ast = _excavator_labor(_est(db, "Астана"))
    shy = _excavator_labor(_est(db, "Шымкент"))
    assert ast.source == "sadi-tariff" and shy.source == "sadi-tariff"
    assert ast.price != shy.price            # регионы дифференцированы
    assert ast.price == round(worker_rates(db, "Астана")["6"])


def test_toggle_off_falls_back_to_seed(db):
    save_settings(db, {"labor_tariff_enabled": False})
    lab = _excavator_labor(_est(db, "Астана"))
    assert lab.source == "seed" and lab.price == 4200  # сид-цена операторов экскаватора


def test_estimate_warns_about_tariffs(db):
    save_settings(db, {"labor_tariff_enabled": True})
    r = _est(db, "Астана")
    assert any("тариф" in w.lower() for w in r.warnings)
