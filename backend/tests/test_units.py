"""Реестр единиц: валидация соответствия вид ресурса ↔ единица."""
from __future__ import annotations

from app.calc.units import unit_known, unit_ok_for_kind


def test_known_units():
    assert unit_known("чел-ч")
    assert unit_known("маш-ч")
    assert unit_known("м³")
    assert not unit_known("попугай")


def test_unit_matches_kind():
    assert unit_ok_for_kind("чел-ч", "labor")
    assert unit_ok_for_kind("маш-ч", "machine")
    assert unit_ok_for_kind("м³", "material")
    assert unit_ok_for_kind("компл", "material")


def test_unit_mismatch_kind_rejected():
    assert not unit_ok_for_kind("чел-ч", "material")   # время — не материал
    assert not unit_ok_for_kind("м³", "labor")         # объём — не труд
    assert not unit_ok_for_kind("маш-ч", "labor")      # машино-час — не труд
    assert not unit_ok_for_kind("попугай", "material")  # неизвестная единица


def test_seed_units_idempotent(db):
    from app.calc.units import seed_units, UNIT_DIMENSION
    from app.models import Unit
    seed_units(db)
    seed_units(db)  # повтор не должен падать/дублировать (PK)
    assert db.query(Unit).count() == len(UNIT_DIMENSION)
    row = db.get(Unit, "чел-ч")
    assert row is not None and row.dimension == "labor_time"
