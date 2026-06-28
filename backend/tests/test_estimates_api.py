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


def _calculated_estimate():
    body = client.post("/api/estimate/sync", json={
        "object_type": "Жилой дом", "demo_mode": True, "use_search": False}).json()
    return body["estimate_id"]


def test_versions_manual_edit_and_rollback():
    eid = _calculated_estimate()
    v1 = client.get(f"/api/estimates/{eid}").json()["current_version"]
    lines = v1["result"]["lines"]

    target = next(l for l in lines if l["no"] != "1.1")
    target["quantity"] = target["quantity"] + 10
    r = client.post(f"/api/estimates/{eid}/manual-edit", json={"lines": lines})
    assert r.status_code == 200
    assert r.json()["version_number"] == 2

    versions = client.get(f"/api/estimates/{eid}/versions").json()
    assert [v["version_number"] for v in versions] == [1, 2]

    r = client.post(f"/api/estimates/{eid}/rollback", json={"version_number": 1})
    assert r.json()["version_number"] == 3
    cur = client.get(f"/api/estimates/{eid}").json()["current_version"]
    assert cur["result"]["totals"]["grand_total"] == v1["result"]["totals"]["grand_total"]
