from fastapi.testclient import TestClient

from app.database import SessionLocal, engine
from app.main import app
from app.seed import run_seed
from app.models import BuildingObject, Estimate

client = TestClient(app)

POLY = {"type": "Polygon", "coordinates": [[
    [76.900, 43.2400], [76.901, 43.2400], [76.901, 43.2405], [76.900, 43.2405], [76.900, 43.2400],
]]}


def test_building_object_table_and_estimate_fk():
    run_seed()
    # колонка object_id есть в estimates
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(estimates)")]
    assert "object_id" in cols
    # объект создаётся и привязывается к смете
    db = SessionLocal()
    try:
        obj = BuildingObject(name="Тест", city="Алматы", lat=43.24, lon=76.9, area_m2=1000.0)
        db.add(obj); db.commit()
        est = Estimate(name="С", object_type="Жилой дом", city="Алматы", object_id=obj.id)
        db.add(est); db.commit()
        assert est.object_id == obj.id
    finally:
        db.close()


def test_object_crud():
    oid = client.post("/api/objects", json={
        "name": "Участок-1", "city": "Алматы", "lat": 43.24, "lon": 76.9, "polygon": POLY}).json()["id"]
    listing = client.get("/api/objects").json()
    assert any(o["id"] == oid and o["area_m2"] > 0 for o in listing)  # площадь из полигона
    got = client.get(f"/api/objects/{oid}").json()
    assert got["object"]["name"] == "Участок-1"
    client.patch(f"/api/objects/{oid}", json={"name": "Новый"})
    assert client.get(f"/api/objects/{oid}").json()["object"]["name"] == "Новый"
    assert client.delete(f"/api/objects/{oid}").status_code == 204
    assert client.get(f"/api/objects/{oid}").status_code == 404


def test_concept_and_estimate_from_object():
    oid = client.post("/api/objects", json={
        "name": "Дом", "city": "Алматы", "lat": 43.24, "lon": 76.9, "polygon": POLY}).json()["id"]
    concept = client.get(f"/api/objects/{oid}/concept", params={"object_type": "Жилой дом"}).json()
    assert concept["building_length"] > 0 and concept["floors"] == 9
    assert concept["city"] == "Алматы"

    r = client.post(f"/api/objects/{oid}/estimate", json=concept)
    assert r.status_code == 200
    eid = r.json()["estimate_id"]
    full = client.get(f"/api/estimates/{eid}").json()
    assert full["object_id"] == oid
    cv = full["current_version"]
    assert cv is not None  # смета сразу рассчитана из концепта
    assert cv["input"]["building_length"] == concept["building_length"]
    # объект показывает привязанную смету
    assert any(e["id"] == eid for e in client.get(f"/api/objects/{oid}").json()["estimates"])


def test_deleting_object_keeps_estimate_and_nulls_link():
    oid = client.post("/api/objects", json={
        "name": "X", "city": "Алматы", "lat": 43.24, "lon": 76.9, "polygon": POLY}).json()["id"]
    eid = client.post(f"/api/objects/{oid}/estimate").json()["estimate_id"]   # body=None → дефолтный концепт
    assert client.delete(f"/api/objects/{oid}").status_code == 204
    full = client.get(f"/api/estimates/{eid}").json()
    assert full["object_id"] is None              # связь обнулена
    assert full["current_version"] is not None    # смета осталась рассчитанной
