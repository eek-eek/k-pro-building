"""Аудит сметы: цена (кейс 1), объём (кейс 3), полнота (кейс 2)."""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from app.calc import build_estimate
from app.calc.estimate_audit import (
    _dependency_gaps, _deterministic, _severity, audit_estimate,
)
from app.main import app
from app.norms import resolve_norm_profile
from app.schemas import BuildingInput, EstimateResult

client = TestClient(app)


def _fresh(db):
    inp = BuildingInput(demo_mode=True, use_search=False, city="Астана",
                        building_length=20, building_width=15, floors=5)
    return build_estimate(db, inp, resolve_norm_profile(db, inp))


def test_severity_grades():
    assert _severity(0.10) == "низкий"
    assert _severity(0.20) == "средний"
    assert _severity(0.50) == "высокий"


def test_clean_estimate_no_findings(db):
    fresh = _fresh(db)
    stored = EstimateResult(**fresh.model_dump())
    assert _deterministic(stored, fresh) == []
    assert _dependency_gaps(stored) == []


def test_price_deviation_detected(db):
    fresh = _fresh(db)
    stored = EstimateResult(**fresh.model_dump())
    ln = next(l for l in stored.lines if "каркас" in l.title.lower())
    ln.material_price = round(ln.material_price * 1.5)  # завышаем
    found = [f for f in _deterministic(stored, fresh) if f.case == "price"]
    assert found and any("завышена" in f.title for f in found)


def test_volume_deviation_detected(db):
    fresh = _fresh(db)
    stored = EstimateResult(**fresh.model_dump())
    ln = next(l for l in stored.lines if l.quantity > 0)
    ln.quantity = round(ln.quantity * 1.4, 2)
    found = [f for f in _deterministic(stored, fresh) if f.case == "volume"]
    assert found and found[0].severity == "высокий"


def test_dependency_gap_detected(db):
    fresh = _fresh(db)
    stored = EstimateResult(**fresh.model_dump())
    # убираем кладочный раствор из строк с газоблоком
    for ln in stored.lines:
        ln.resources = [r for r in ln.resources if r.code != "masonry_glue"]
    codes = {r.code for ln in stored.lines for r in ln.resources}
    if "aerated_block" in codes:                         # только если кладка вообще есть
        gaps = _dependency_gaps(stored)
        assert any("раствор" in f.detail.lower() for f in gaps)
        assert all(f.severity == "высокий" for f in gaps)


def test_audit_endpoint_clean(db):
    r = client.post("/api/estimate/sync", json={
        "city": "Астана", "project_name": "audit", "building_length": 20,
        "building_width": 15, "floors": 5, "demo_mode": True, "use_search": False})
    eid = r.json()["estimate_id"]
    rep = client.post(f"/api/estimates/{eid}/audit").json()
    assert "findings" in rep and "summary" in rep
    assert rep["checked_lines"] > 0
    # demo без ключа проверяющего → LLM-часть полноты не запускалась
    assert rep["llm_used"] is False


def test_audit_endpoint_404_uncalculated():
    assert client.post("/api/estimates/999999/audit").status_code == 404
