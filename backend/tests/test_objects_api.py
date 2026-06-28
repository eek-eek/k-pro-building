import time

from fastapi.testclient import TestClient

from app.database import SessionLocal, engine
from app.main import app
from app.seed import run_seed
from app.models import BuildingObject, Estimate
from app.zoning import wfs as _wfs

client = TestClient(app)

POLY = {"type": "Polygon", "coordinates": [[
    [76.900, 43.2400], [76.901, 43.2400], [76.901, 43.2405], [76.900, 43.2405], [76.900, 43.2400],
]]}


def _wait_job(job_id, tries=200):
    """Смета из объекта считается фоновой задачей — ждём терминального статуса."""
    for _ in range(tries):
        st = client.get(f"/api/estimate/{job_id}").json()
        if st["status"] in ("done", "error"):
            return st
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} не завершилась за отведённое время")


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


def test_building_object_has_zone_columns():
    run_seed()
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(building_objects)")]
    for c in ("zone_status", "zone_land_use", "zone_kad_nomer", "zone_note", "zone_checked_at"):
        assert c in cols, f"нет колонки {c}"


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
    body = r.json()
    eid = body["estimate_id"]
    assert body["job_id"]  # расчёт идёт фоновой задачей (прогресс-оверлей)
    assert _wait_job(body["job_id"])["status"] == "done"
    full = client.get(f"/api/estimates/{eid}").json()
    assert full["object_id"] == oid
    cv = full["current_version"]
    assert cv is not None  # смета рассчитана из концепта
    assert cv["input"]["building_length"] == concept["building_length"]
    # объект показывает привязанную смету
    assert any(e["id"] == eid for e in client.get(f"/api/objects/{oid}").json()["estimates"])


def test_deleting_object_keeps_estimate_and_nulls_link():
    oid = client.post("/api/objects", json={
        "name": "X", "city": "Алматы", "lat": 43.24, "lon": 76.9, "polygon": POLY}).json()["id"]
    body = client.post(f"/api/objects/{oid}/estimate").json()   # body=None → дефолтный концепт
    eid = body["estimate_id"]
    assert _wait_job(body["job_id"])["status"] == "done"        # дождаться расчёта
    assert client.delete(f"/api/objects/{oid}").status_code == 204
    full = client.get(f"/api/estimates/{eid}").json()
    assert full["object_id"] is None              # связь обнулена
    assert full["current_version"] is not None    # смета осталась рассчитанной


def test_delete_estimate_with_job_row():
    """Смета из объекта теперь рассчитывается job-задачей и имеет строку в jobs.
    Её удаление не должно падать на FK jobs.estimate_id → estimates.id."""
    oid = client.post("/api/objects", json={
        "name": "Удаляемый", "city": "Алматы", "lat": 43.24, "lon": 76.9, "polygon": POLY}).json()["id"]
    body = client.post(f"/api/objects/{oid}/estimate").json()
    assert _wait_job(body["job_id"])["status"] == "done"
    eid = body["estimate_id"]
    assert client.delete(f"/api/estimates/{eid}").status_code == 204
    assert client.get(f"/api/estimates/{eid}").status_code == 404


def test_check_zone_saves_verdict(monkeypatch):
    plot = {"features": [{
        "geometry": {"type": "MultiPolygon", "coordinates": [[[
            [76.944, 43.237], [76.946, 43.237], [76.946, 43.239], [76.944, 43.239], [76.944, 43.237]]]]},
        "properties": {"kad_nomer": "20313005104",
                       "tsn_ru": "для строительства жилого дома", "squ": 5000}}]}
    monkeypatch.setattr(_wfs, "_wfs_features",
                        lambda tn, lat, lon, count=5: plot if tn == "openmap:land_plots" else {"features": []})
    oid = client.post("/api/objects", json={
        "name": "Z", "city": "Алматы", "lat": 43.238, "lon": 76.945, "polygon": POLY}).json()["id"]
    v = client.post(f"/api/objects/{oid}/check-zone").json()
    assert v["status"] == "allowed" and v["kad_nomer"] == "20313005104"
    # вердикт сохранён и виден в карточке
    got = client.get(f"/api/objects/{oid}").json()
    assert got["zone_status"] == "allowed"
    assert "жилого" in got["zone_land_use"]


def test_check_zone_404_for_missing_object():
    assert client.post("/api/objects/999999/check-zone").status_code == 404


def test_zoning_wms_config():
    cfg = client.get("/api/zoning/wms", params={"city": "Алматы"}).json()
    assert cfg["url"] and cfg["layers"]
