"""Ревизия цен материалов по SADI в расчёте сметы."""
from __future__ import annotations

from app.calc import build_estimate
from app.calc.material_revision import REVISION, apply_material_revision
from app.norms import resolve_norm_profile
from app.schemas import BuildingInput, ResourceLine
from app.settings_service import save_settings


def _est(db):
    inp = BuildingInput(demo_mode=True, use_search=False, city="Астана",
                        building_length=20, building_width=15, floors=5)
    return build_estimate(db, inp, resolve_norm_profile(db, inp))


def _mat_price(res, code):
    for ln in res.lines:
        for r in (ln.resources or []):
            if r.code == code:
                return r
    return None


def test_apply_revision_only_materials():
    res = [
        ResourceLine(code="xps", name="ЭППС", kind="material", unit="м³", consumption=1, price=28000),
        ResourceLine(code="concreter", name="Бетонщик", kind="labor", unit="чел-ч", consumption=1, price=3500),
        ResourceLine(code="unknown_mat", name="X", kind="material", unit="шт", consumption=1, price=100),
    ]
    applied = apply_material_revision(res, "2026-07-01")
    assert applied is True
    assert res[0].price == 43000 and res[0].source == "sadi-rev"  # в словаре
    assert res[1].price == 3500                                   # труд не тронут
    assert res[2].price == 100                                    # нет в словаре — как есть


def test_revision_not_lowering_seed_codes():
    # коды, где сид ≥ SADI, в словарь не входят → не понижаются
    for code in ("concrete_b25", "rebar_a500", "window_pvc", "aerated_block"):
        assert code not in REVISION


def test_estimate_applies_revision_when_on(db):
    save_settings(db, {"material_revision_enabled": True})
    r = _est(db)
    xps = _mat_price(r, "xps")
    if xps is not None:                       # ЭППС встречается в утеплении
        assert xps.price == 43000 and xps.source == "sadi-rev"
    assert any("ревизирован" in w.lower() for w in r.warnings)


def test_estimate_off_keeps_seed(db):
    save_settings(db, {"material_revision_enabled": False})
    r = _est(db)
    xps = _mat_price(r, "xps")
    if xps is not None:
        assert xps.price == 28000 and xps.source != "sadi-rev"
    assert not any("ревизирован" in w.lower() for w in r.warnings)
