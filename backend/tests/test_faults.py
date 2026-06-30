"""Скрининг разломов/сейсмики: чистая геометрия, детерминирован."""
from fastapi.testclient import TestClient

from app.main import app
from app.zoning.faults import FAULTS, assess_faults, nearest_fault

client = TestClient(app)


def test_point_on_fault_is_avoid():
    # вершина Заилийского разлома → фактически на разломе
    v = assess_faults(43.18, 76.95, "Алматы")
    assert v.status == "avoid"
    assert v.max_floors == 2
    assert v.distance_m < 300
    assert "Заилийский" in v.nearest_fault


def test_point_near_fault_is_caution_and_capped():
    # ~1 км севернее разлома → повышенный риск, этажность зажата
    v = assess_faults(43.189, 76.95, "Алматы")
    assert v.status == "caution"
    assert v.max_floors == 5            # min(NEAR_FLOORS=5, сейсмокап 9)
    assert 300 < v.distance_m <= 1500


def test_far_high_seismic_uses_seismic_cap():
    # далеко от разломов, но Алматы (9 баллов) → сейсмический предел этажности
    v = assess_faults(43.40, 76.95, "Алматы")
    assert v.status == "ok"
    assert v.intensity == 9
    assert v.max_floors == 9
    assert v.distance_m > 1500


def test_far_low_seismic_has_no_floor_cap():
    # Астана: вдали от разломов и низкая сейсмичность → ограничений по высоте нет
    v = assess_faults(51.13, 71.43, "Астана")
    assert v.status == "ok"
    assert v.intensity == 6
    assert v.max_floors is None


def test_nearest_fault_returns_finite_distance():
    name, dist = nearest_fault(43.238, 76.889)
    assert name
    assert dist >= 0 and dist != float("inf")


def test_faults_endpoint_returns_feature_collection():
    r = client.get("/api/zoning/faults")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == len(FAULTS["features"]) >= 1
    assert body["features"][0]["geometry"]["type"] == "LineString"


def test_object_get_includes_fault_screening():
    # объект в Алматы → ответ карточки содержит блок faults
    db_obj = client.post("/api/objects", json={
        "name": "Разлом-тест", "city": "Алматы", "lat": 43.18, "lon": 76.95,
        "polygon": {"type": "Polygon", "coordinates": [[
            [76.949, 43.179], [76.951, 43.179], [76.951, 43.181],
            [76.949, 43.181], [76.949, 43.179]]]},
    }).json()
    oid = db_obj["id"]
    data = client.get(f"/api/objects/{oid}").json()
    assert "faults" in data
    assert data["faults"]["status"] == "avoid"
    client.delete(f"/api/objects/{oid}")
