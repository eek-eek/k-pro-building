"""Тесты резолва нормативного профиля и кэширования."""
from __future__ import annotations

from app.models import KnowledgeCache
from app.norms import resolve_norm_profile
from app.norms.defaults import CATEGORY_META
from app.schemas import BuildingInput


def _input(**kw) -> BuildingInput:
    base = dict(demo_mode=True, use_search=False)
    base.update(kw)
    return BuildingInput(**base)


def test_profile_has_full_param_set(db):
    inp = _input(object_type="Офис")
    profile = resolve_norm_profile(db, inp)
    for category in CATEGORY_META:
        assert category in profile.params, f"нет коэффициента {category}"


def test_cache_hit_on_second_call(db):
    inp = _input(object_type="Склад", structure_type="Металлокаркас")
    first = resolve_norm_profile(db, inp)
    assert first.from_cache is False
    second = resolve_norm_profile(db, inp)
    assert second.from_cache is True
    # сигнатуры совпадают
    assert first.signature == second.signature
    cached = db.query(KnowledgeCache).filter_by(signature=first.signature).count()
    assert cached == 1


def test_signature_changes_with_structure(db):
    a = _input(structure_type="Монолитный железобетон").signature()
    b = _input(structure_type="Кирпич/газоблок").signature()
    assert a != b


def test_documents_seeded_per_object_type(db):
    profile = resolve_norm_profile(db, _input(object_type="Жилой дом"))
    codes = {s.code for s in profile.sources}
    assert "ТР РК №435-2023" in codes  # общий обязательный
    assert any("3.02-01-2023" in c for c in codes)  # профильный жилой
