from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _calc():
    return client.post("/api/estimate/sync", json={
        "object_type": "Жилой дом", "demo_mode": True, "use_search": False}).json()["estimate_id"]


def test_price_sources_endpoint():
    names = {s["name"] for s in client.get("/api/price-sources").json()}
    assert {"curated", "satu"} <= names


def test_suggest_curated_prices():
    eid = _calc()
    r = client.post(f"/api/estimates/{eid}/suggest-material-prices", json={"source": "curated"})
    assert r.status_code == 200
    sugg = r.json()["suggestions"]
    assert sugg
    assert any(v["source"] == "curated" for v in sugg.values())


def test_suggest_on_missing_estimate_404():
    r = client.post("/api/estimates/999999/suggest-material-prices", json={"source": "curated"})
    assert r.status_code == 404
