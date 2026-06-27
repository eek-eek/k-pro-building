"""Тесты геометрии, объёмов и арифметики сметы."""
from __future__ import annotations

from app.calc import build_estimate
from app.calc.geometry import derive
from app.calc.volumes import compute_volumes
from app.norms import resolve_norm_profile
from app.schemas import BuildingInput


def _input(**kw) -> BuildingInput:
    base = dict(demo_mode=True, use_search=False)
    base.update(kw)
    return BuildingInput(**base)


def test_geometry_basic():
    geo = derive(_input(building_length=50, building_width=20, floors=5, floor_height=3))
    assert geo.build_area == 1000
    assert geo.perimeter == 140
    assert geo.total_height == 15
    assert geo.building_volume == 15000
    assert geo.facade_area == 140 * 15


def test_geometry_from_area_when_no_dims():
    geo = derive(_input(building_length=0, building_width=0, total_area=2000, floors=4))
    assert geo.build_area == 500  # 2000 / 4


def test_volume_relations(db):
    inp = _input(object_type="Жилой дом")
    profile = resolve_norm_profile(db, inp)
    vols = compute_volumes(inp, profile)

    total_concrete = vols["foundation_concrete"].quantity + vols["frame_concrete"].quantity
    rebar_kg = profile.value("rebar_kg_per_m3", 100)
    assert abs(vols["rebar"].quantity - total_concrete * rebar_kg / 1000) < 0.5

    formwork_ratio = profile.value("formwork_m2_per_m3", 2.5)
    assert abs(vols["formwork"].quantity - total_concrete * formwork_ratio) < 1.0


def test_estimate_totals_chain(db):
    inp = _input(overhead_pct=8, contingency_pct=5, vat_pct=12)
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    t = r.totals

    assert t.direct > 0
    assert t.overhead == round(t.direct * 8 / 100)
    assert t.subtotal_with_overhead == t.direct + t.overhead
    assert t.contingency == round(t.subtotal_with_overhead * 5 / 100)
    assert t.subtotal_with_contingency == t.subtotal_with_overhead + t.contingency
    assert t.vat == round(t.subtotal_with_contingency * 12 / 100)
    assert t.grand_total == t.subtotal_with_contingency + t.vat


def test_estimate_has_lines_and_sources(db):
    inp = _input()
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    assert len(r.lines) > 5
    assert len(r.sources) > 0
    # сумма итогов строк по разделам не превышает прямые затраты (с учётом подготовки)
    assert sum(r.section_totals.values()) == r.totals.direct


def test_no_finishing_when_without_finish(db):
    inp = _input(finish_level="Без отделки")
    profile = resolve_norm_profile(db, inp)
    vols = compute_volumes(inp, profile)
    assert vols["screed"].quantity == 0
    assert vols["wall_finish"].quantity == 0


def test_works_filter_limits_sections(db):
    inp = _input(works=["Кровля"])
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    sections = {ln.section for ln in r.lines}
    assert any("Кровля" in s for s in sections)
    assert not any("Электромонтаж" in s for s in sections)
