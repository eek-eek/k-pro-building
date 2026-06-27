from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_sync_calc_creates_estimate_with_initial_version():
    r = client.post("/api/estimate/sync", json={
        "object_type": "Жилой дом", "demo_mode": True, "use_search": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["estimate_id"] >= 1
    assert body["version_number"] == 1
    assert body["result"]["totals"]["grand_total"] > 0
