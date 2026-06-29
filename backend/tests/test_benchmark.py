"""Внутренний справочник цен (бенчмаркинг) — приоритет над сидовыми ценами."""
import base64

from fastapi.testclient import TestClient

from app.main import app
from app.calc.resource_catalog import db_snapshot_for, BENCHMARK_PRICE_LEVEL
from app.models import WorkResource

_AUTH = "Basic " + base64.b64encode(b"admin:admin12345").decode()
client = TestClient(app, headers={"Authorization": _AUTH})


def test_benchmark_overrides_seed_in_snapshot(db):
    # бенчмарк-цена перебивает сидовую; чистим за собой (общая сессия БД)
    row = WorkResource(work_key="frame_concrete", code="bench_concrete",
                       name="Бетон (бенчмарк)", kind="material", unit="м³",
                       consumption=1.0, price=99999, region="KZ",
                       price_level=BENCHMARK_PRICE_LEVEL, source="benchmark")
    db.add(row)
    db.commit()
    try:
        res = db_snapshot_for(db, "frame_concrete", "KZ")
        assert any(r.code == "bench_concrete" for r in res)
        assert all(r.source == "benchmark" for r in res)  # бенчмарк all-or-nothing
    finally:
        db.delete(row)
        db.commit()


def test_benchmark_crud_requires_auth():
    anon = TestClient(app)
    assert anon.get("/api/benchmark").status_code == 401
    assert anon.post("/api/benchmark", json={"work_key": "x", "code": "y",
                     "kind": "material", "unit": "м³"}).status_code == 401


def test_benchmark_add_list_delete():
    r = client.post("/api/benchmark", json={
        "work_key": "test_bm_work", "code": "bm_roof", "name": "Кровля бенчмарк",
        "kind": "material", "unit": "м²", "consumption": 1.0, "price": 8500, "region": "KZ"})
    assert r.status_code == 200
    rid = r.json()["id"]
    listing = client.get("/api/benchmark").json()
    assert any(x["id"] == rid and x["price"] == 8500 for x in listing)
    assert client.delete(f"/api/benchmark/{rid}").status_code == 204
    assert all(x["id"] != rid for x in client.get("/api/benchmark").json())


def test_benchmark_rejects_bad_unit():
    r = client.post("/api/benchmark", json={
        "work_key": "z", "code": "bad", "kind": "labor", "unit": "м³",
        "consumption": 1, "price": 100})
    assert r.status_code == 400  # labor должен измеряться в чел-ч, не м³
