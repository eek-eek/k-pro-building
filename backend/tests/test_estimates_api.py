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


def test_manual_edit_noop_does_not_create_version():
    eid = _calculated_estimate()
    v1 = client.get(f"/api/estimates/{eid}").json()["current_version"]
    lines = v1["result"]["lines"]
    # сохраняем без единой правки
    r = client.post(f"/api/estimates/{eid}/manual-edit", json={"lines": lines})
    assert r.status_code == 200
    assert r.json().get("unchanged") is True
    assert r.json()["version_number"] == v1["version_number"]   # версия не выросла
    assert [v["version_number"] for v in client.get(f"/api/estimates/{eid}/versions").json()] == [1]

    # а реальная правка — создаёт версию 2
    target = next(l for l in lines if l["no"] != "1.1")
    target["quantity"] = target["quantity"] + 1
    r2 = client.post(f"/api/estimates/{eid}/manual-edit", json={"lines": lines})
    assert r2.json().get("unchanged") is not True
    assert r2.json()["version_number"] == 2


def test_verify_norms_checks_links_and_keeps_single_version(monkeypatch):
    from app.schemas import NormProfile, NormSource
    eid = _calculated_estimate()
    cur = client.get(f"/api/estimates/{eid}").json()["current_version"]
    srcs = [NormSource(**s) for s in cur["result"]["sources"]]
    # без сети: ссылки = ок; норм-резолв возвращает те же источники
    monkeypatch.setattr("app.api.routes._check_link", lambda url: True)
    monkeypatch.setattr("app.api.routes.resolve_norm_profile",
                        lambda db, inp: NormProfile(signature="x",
                                                    object_type=inp.object_type, sources=srcs))
    r = client.post(f"/api/estimates/{eid}/verify-norms")
    assert r.status_code == 200
    assert r.json()["checked"] == len(srcs)
    assert all(s["link_ok"] is True for s in r.json()["sources"] if s["url"])
    # версия не выросла (обновление источников на месте)
    assert [v["version_number"] for v in client.get(f"/api/estimates/{eid}/versions").json()] == [1]
    cur2 = client.get(f"/api/estimates/{eid}").json()["current_version"]
    assert any(s.get("link_ok") is True for s in cur2["result"]["sources"])
