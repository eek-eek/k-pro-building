from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
DRAFT = {"name": "Тестовый дом", "input": {"object_type": "Жилой дом",
         "demo_mode": True, "use_search": False}}


def test_create_list_get_patch_delete_estimate():
    cid = client.post("/api/estimates", json=DRAFT).json()["id"]
    listing = client.get("/api/estimates").json()
    assert any(c["id"] == cid and c["status"] == "draft" for c in listing)

    got = client.get(f"/api/estimates/{cid}").json()
    assert got["estimate"]["name"] == "Тестовый дом"

    client.patch(f"/api/estimates/{cid}", json={"name": "Новое имя"})
    assert client.get(f"/api/estimates/{cid}").json()["estimate"]["name"] == "Новое имя"

    assert client.delete(f"/api/estimates/{cid}").status_code == 204
    assert client.get(f"/api/estimates/{cid}").status_code == 404
