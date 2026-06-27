from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _calculated_estimate():
    body = client.post("/api/estimate/sync", json={
        "object_type": "Жилой дом", "demo_mode": True, "use_search": False}).json()
    return body["estimate_id"]


def test_list_recommendations_returns_computed_costs():
    eid = _calculated_estimate()
    recs = client.get(f"/api/estimates/{eid}/recommendations").json()
    assert recs, "ожидались рекомендации"
    for r in recs:
        assert r["estimated_total"] > 0
        assert {"key", "title", "norm", "unit", "quantity", "basis"} <= set(r)


def test_add_recommendation_creates_version_and_raises_total():
    eid = _calculated_estimate()
    before = client.get(f"/api/estimates/{eid}").json()["current_version"]
    grand_before = before["result"]["totals"]["grand_total"]
    key = client.get(f"/api/estimates/{eid}/recommendations").json()[0]["key"]

    r = client.post(f"/api/estimates/{eid}/recommendations", json={"key": key})
    assert r.status_code == 200
    assert r.json()["version_number"] == 2
    assert r.json()["result"]["totals"]["grand_total"] > grand_before

    # выбранная позиция исчезает из списка рекомендаций
    keys_after = {r["key"] for r in client.get(f"/api/estimates/{eid}/recommendations").json()}
    assert key not in keys_after


def test_add_unknown_recommendation_returns_404():
    eid = _calculated_estimate()
    r = client.post(f"/api/estimates/{eid}/recommendations", json={"key": "nope"})
    assert r.status_code == 404


def test_recommendations_on_missing_estimate():
    assert client.get("/api/estimates/999999/recommendations").json() == []
    r = client.post("/api/estimates/999999/recommendations", json={"key": "geodesy"})
    assert r.status_code == 404
