"""Кросс-проверка норм вторым провайдером (ансамбль) — через monkeypatch фабрики."""
from __future__ import annotations

import pytest

import app.llm.factory as factory
from app.norms.extractor import cross_check_params
from app.schemas import BuildingInput, NormParam
from app.settings_service import save_settings


@pytest.fixture(autouse=True)
def _reset_cross_check(db):
    """Не протекать настройкой кросс-проверки в другие тесты (общая сессия БД)."""
    yield
    save_settings(db, {"cross_check_enabled": False})


class _Fake:
    name = "openai"
    available = True

    def __init__(self, params):
        self._params = params

    def extract_json(self, system, user, *, use_search=False):
        return {"params": self._params}, []


def _enable(db, provider="openai"):
    save_settings(db, {"llm_provider": "anthropic",
                       "cross_check_enabled": True, "cross_check_provider": provider})


def _primary():
    return {"rebar_kg_per_m3": NormParam(category="rebar_kg_per_m3", value=100,
                                         unit="кг/м³", source="llm", confidence=0.6)}


def _inp():
    return BuildingInput(object_type="Жилой дом")


def test_agreement_bumps_confidence(db, monkeypatch):
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([{"category": "rebar_kg_per_m3", "value": 105, "unit": "кг/м³"}]))
    params, cc = cross_check_params(db, _inp(), [], _primary())
    assert cc.ran is True and cc.agreed == 1 and cc.disputed == 0
    assert params["rebar_kg_per_m3"].confidence > 0.6
    assert "подтверждено" in params["rebar_kg_per_m3"].note


def test_disagreement_flags_review(db, monkeypatch):
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([{"category": "rebar_kg_per_m3", "value": 200, "unit": "кг/м³"}]))
    params, cc = cross_check_params(db, _inp(), [], _primary())
    assert cc.disputed == 1
    assert params["rebar_kg_per_m3"].needs_review is True
    assert "расхождение" in params["rebar_kg_per_m3"].note


def test_both_zero_is_agreement(db, monkeypatch):
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([{"category": "finishing_factor", "value": 0, "unit": "коэф."}]))
    prim = {"finishing_factor": NormParam(category="finishing_factor", value=0.0,
                                          unit="коэф.", source="llm", confidence=0.6)}
    params, cc = cross_check_params(db, _inp(), [], prim)
    assert cc.agreed == 1 and cc.disputed == 0  # 0 vs 0 — согласие, не астрономический rel


def test_unit_mismatch_flags_review(db, monkeypatch):
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([{"category": "wall_insulation_thickness_m", "value": 12, "unit": "см"}]))
    prim = {"wall_insulation_thickness_m": NormParam(category="wall_insulation_thickness_m",
                                                     value=0.12, unit="м", source="llm", confidence=0.6)}
    params, cc = cross_check_params(db, _inp(), [], prim)
    assert cc.disputed == 1
    assert "единицы расходятся" in params["wall_insulation_thickness_m"].note


def test_disabled_returns_untouched(db, monkeypatch):
    save_settings(db, {"cross_check_enabled": False})
    called = {"n": 0}
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: called.__setitem__("n", called["n"] + 1) or _Fake([]))
    params, cc = cross_check_params(db, _inp(), [], _primary())
    assert cc.enabled is False and cc.ran is False
    assert called["n"] == 0  # проверяющий не строился


def test_empty_primary_no_second_call(db, monkeypatch):
    _enable(db)
    called = {"n": 0}
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: called.__setitem__("n", called["n"] + 1) or _Fake([]))
    params, cc = cross_check_params(db, _inp(), [], {})
    assert cc.ran is False and called["n"] == 0  # пустой основной → без 2-го вызова


def test_unreadable_verifier_degrades(db, monkeypatch):
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([]))  # вернул 0 параметров
    params, cc = cross_check_params(db, _inp(), [], _primary())
    assert cc.ran is False and "нечитаемый" in cc.reason
    assert "не дала значение" not in params["rebar_kg_per_m3"].note  # без ложного missing


def test_resolver_attaches_cross_check(db, monkeypatch):
    import app.norms.extractor as extractor
    from app.norms import resolve_norm_profile
    _enable(db)
    monkeypatch.setattr(extractor, "extract_params",
                        lambda d, i, docs: ({"rebar_kg_per_m3": NormParam(
                            category="rebar_kg_per_m3", value=100, unit="кг/м³",
                            source="llm", confidence=0.6)}, [], []))
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([{"category": "rebar_kg_per_m3", "value": 105, "unit": "кг/м³"}]))
    inp = BuildingInput(object_type="Жилой дом", demo_mode=False, use_search=False)
    prof = resolve_norm_profile(db, inp, force=True)  # мимо кэша
    assert prof.cross_check is not None and prof.cross_check.ran is True
    assert prof.cross_check.agreed >= 1


def test_estimate_warning_from_cross_check(db):
    from app.calc import build_estimate
    from app.schemas import CrossCheck
    inp = BuildingInput(demo_mode=True, use_search=False, object_type="Жилой дом")
    from app.norms import resolve_norm_profile
    prof = resolve_norm_profile(db, inp)
    prof.cross_check = CrossCheck(enabled=True, ran=True, verifier="openai",
                                  agreed=3, disputed=1)
    r = build_estimate(db, inp, prof)
    assert any("кросс-проверку (openai)" in w.lower() for w in r.warnings)
