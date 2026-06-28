"""Каталог из БД даёт те же удельные цены, что встроенный COMPOSITIONS (нет регрессии)."""
from __future__ import annotations

from app.calc.resource_catalog import (
    COMPOSITIONS, db_snapshot_for, rollup, snapshot_for,
)


def test_db_snapshot_parity_per_work(db):
    """Для каждой работы ролл-ап из БД совпадает с ролл-апом из кода."""
    for key in COMPOSITIONS:
        assert rollup(db_snapshot_for(db, key)) == rollup(snapshot_for(key)), key


def test_db_snapshot_fallback_when_absent(db):
    """Нет данных для ключа → фолбэк на встроенный состав (или пусто)."""
    assert db_snapshot_for(db, "no_such_work") == snapshot_for("no_such_work")  # == []


def test_build_estimate_uses_db_no_regression(db):
    """build_estimate на каталоге из БД даёт ту же удельную цену каркаса, что из кода."""
    from app.calc import build_estimate
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput

    inp = BuildingInput(demo_mode=True, use_search=False)
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    frame = next(ln for ln in r.lines if ln.title == "Бетон монолитного каркаса")
    # удельная цена = материал+труд+машины из каталога (БД) = как в COMPOSITIONS
    mat, lab, mach = rollup(snapshot_for("frame_concrete"))
    unit_cost = mat + lab + mach
    assert frame.material_price + frame.labor_price + frame.machine_price == unit_cost
    assert frame.total == round(frame.quantity * unit_cost)
