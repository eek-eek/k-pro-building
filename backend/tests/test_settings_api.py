from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_settings_shape_and_catalog():
    s = client.get("/api/settings").json()
    assert "provider" in s and "model" in s and "catalog" in s
    assert "masked_key" in s and "has_key" in s
    assert "gemini" in s["catalog"]


def test_put_settings_masks_key_and_persists_provider():
    client.put("/api/settings", json={"provider": "anthropic",
               "api_key": "sk-ant-secret-1234567890", "model": "claude-opus-4-8"})
    s = client.get("/api/settings").json()
    assert s["provider"] == "anthropic"
    assert s["model"] == "claude-opus-4-8"
    assert s["has_key"] is True
    assert "secret" not in s["masked_key"]
    assert "•" in s["masked_key"]


def test_put_settings_keeps_key_when_masked_value_resent():
    client.put("/api/settings", json={"provider": "anthropic",
               "api_key": "sk-ant-keepme-9999999999"})
    masked = client.get("/api/settings").json()["masked_key"]
    client.put("/api/settings", json={"provider": "anthropic", "api_key": masked})
    assert client.get("/api/settings").json()["has_key"] is True


def test_test_connection_demo_returns_not_ok():
    r = client.post("/api/settings/test", json={"provider": "demo"}).json()
    assert r["ok"] is False
