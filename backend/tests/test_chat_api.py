import app.chat.editor as editor
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class _FakeProvider:
    available = True
    def extract_json(self, system, user, *, use_search=False):
        import json as _j
        start = user.index("[")
        end = user.index("]", start) + 1
        lines = _j.loads(user[start:end])
        kept = lines[:-1]  # remove the last line
        return {"reply": "Убрал последнюю строку.", "lines": kept}, []


def _calc():
    return client.post("/api/estimate/sync", json={
        "object_type": "Жилой дом", "demo_mode": True, "use_search": False}).json()["estimate_id"]


def test_chat_unavailable_returns_409(monkeypatch):
    eid = _calc()
    r = client.post(f"/api/estimates/{eid}/chat", json={"message": "убери кровлю"})
    assert r.status_code == 409
    assert "провайдер" in r.json()["detail"].lower()


def test_chat_edit_creates_version_and_messages(monkeypatch):
    eid = _calc()
    monkeypatch.setattr(editor, "get_provider", lambda: _FakeProvider())
    r = client.post(f"/api/estimates/{eid}/chat", json={"message": "убери последнюю строку"})
    assert r.status_code == 200
    body = r.json()
    assert body["version_number"] == 2
    assert body["reply"]
    msgs = client.get(f"/api/estimates/{eid}/chat").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
