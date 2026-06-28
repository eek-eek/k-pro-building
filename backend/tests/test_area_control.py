"""Контроль общей площади по габаритам (автозамена) + целочисленная этажность."""
from app.schemas import BuildingInput
from app.calc.estimate import build_estimate
from app.norms.resolver import resolve_norm_profile


def _calc(db, **kw):
    inp = BuildingInput(object_type="Жилой дом", demo_mode=True, use_search=False, **kw)
    profile = resolve_norm_profile(db, inp)
    return inp, build_estimate(db, inp, profile)


def test_total_area_clamped_when_exceeds_geometry(db):
    # box 10×15, 3 этажа → физический максимум 450 м². Запрос 999 → обрезать до 450.
    inp, res = _calc(db, building_length=10, building_width=15, floors=3,
                     total_area=999, form="box")
    assert inp.total_area == 450
    assert any("максимум" in w and "уменьшена" in w for w in res.warnings)


def test_total_area_kept_when_within_geometry(db):
    inp, res = _calc(db, building_length=10, building_width=15, floors=3,
                     total_area=400, form="box")
    assert inp.total_area == 400  # в пределах максимума 450 — не трогаем
    assert not any("физический максимум" in w for w in res.warnings)


def test_total_area_not_clamped_without_dimensions(db):
    # без габаритов физический максимум не определить — площадь не трогаем
    inp, res = _calc(db, building_length=0, building_width=0, floors=5, total_area=2000)
    assert inp.total_area == 2000
    assert not any("физический максимум" in w for w in res.warnings)


def test_form_factor_reduces_max_area(db):
    # башня footprint 0.70 → максимум 10×15×0.70×3 = 315 (меньше, чем у бруска)
    inp, res = _calc(db, building_length=10, building_width=15, floors=3,
                     total_area=999, form="tower")
    assert inp.total_area == round(10 * 15 * 0.70 * 3)  # 315
    assert any("уменьшена" in w for w in res.warnings)


def test_floors_coerced_to_integer():
    # этажи не могут быть дробными — округляются, минимум 1
    assert BuildingInput(floors=3.5).floors == 4
    assert BuildingInput(floors=2.2).floors == 2
    assert BuildingInput(floors=0).floors == 1
