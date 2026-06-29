"""Внутренний справочник цен (бенчмаркинг) — приоритет над сидовыми ценами."""
from fastapi.testclient import TestClient

from app.main import app
from app.calc.resource_catalog import db_snapshot_for, BENCHMARK_PRICE_LEVEL
from app.models import WorkResource

client = TestClient(app)  # справочник цен — открытый раздел, без авторизации


def test_benchmark_overlays_by_code_keeps_rest(db):
    # Бенчмарк ОДНОГО кода перекрывает его цену, остальной состав работы сохраняется.
    base = db_snapshot_for(db, "frame_concrete", "KZ")
    assert len(base) >= 2
    code0 = base[0].code
    row = WorkResource(work_key="frame_concrete", code=code0, name=base[0].name,
                       kind=base[0].kind, unit=base[0].unit, consumption=base[0].consumption,
                       price=88888, region="KZ", price_level=BENCHMARK_PRICE_LEVEL,
                       source="benchmark")
    db.add(row)
    db.commit()
    try:
        res = db_snapshot_for(db, "frame_concrete", "KZ")
        assert len(res) == len(base)  # состав не схлопнулся
        over = next(r for r in res if r.code == code0)
        assert over.price == 88888 and over.source == "benchmark"
        # прочие ресурсы остались сидовыми
        assert any(r.code != code0 and r.source != "benchmark" for r in res)
    finally:
        db.delete(row)
        db.commit()


def test_benchmark_adds_new_code(db):
    base = db_snapshot_for(db, "frame_concrete", "KZ")
    row = WorkResource(work_key="frame_concrete", code="bench_new", name="Доп. ресурс",
                       kind="material", unit="м³", consumption=0.1, price=5000,
                       region="KZ", price_level=BENCHMARK_PRICE_LEVEL, source="benchmark")
    db.add(row)
    db.commit()
    try:
        res = db_snapshot_for(db, "frame_concrete", "KZ")
        assert len(res) == len(base) + 1
        assert any(r.code == "bench_new" for r in res)
    finally:
        db.delete(row)
        db.commit()


def test_benchmark_endpoints_are_public():
    # отдельный раздел, не за авторизацией Настроек
    assert client.get("/api/benchmark").status_code == 200


def test_benchmark_add_list_delete():
    r = client.post("/api/benchmark", json={
        "work_key": "roof", "code": "bm_roof", "name": "Кровля бенчмарк",
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
