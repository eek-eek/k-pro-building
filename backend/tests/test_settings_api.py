import base64

from fastapi.testclient import TestClient
from app.main import app

# Настройки за авторизацией — клиент шлёт admin/admin12345.
_AUTH = "Basic " + base64.b64encode(b"admin:admin12345").decode()
client = TestClient(app, headers={"Authorization": _AUTH})


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


def test_get_settings_has_per_provider_keys():
    s = client.get("/api/settings").json()
    assert "keys" in s and "models" in s and "has_keys" in s
    for p in ("gemini", "anthropic", "openai"):
        assert p in s["keys"] and p in s["models"] and p in s["has_keys"]


def test_keys_isolated_per_provider():
    """Ключ одного провайдера не должен попадать в другой (баг «один ключ на всех»)."""
    client.put("/api/settings", json={"provider": "anthropic", "api_key": "sk-ant-iso-1111111111"})
    client.put("/api/settings", json={"provider": "openai", "api_key": "sk-openai-iso-2222222222"})
    s = client.get("/api/settings").json()
    assert s["has_keys"]["anthropic"] is True
    assert s["has_keys"]["openai"] is True
    assert s["keys"]["anthropic"] != s["keys"]["openai"]  # разные ключи → разные masked


def test_masked_value_never_saved_as_key():
    """Присланная masked-строка (с «•») не должна перезаписать реальный ключ мусором."""
    client.put("/api/settings", json={"provider": "openai", "api_key": "sk-openai-real-3333333333"})
    masked = client.get("/api/settings").json()["keys"]["openai"]
    assert "•" in masked
    client.put("/api/settings", json={"provider": "openai", "api_key": masked})  # повтор masked
    s = client.get("/api/settings").json()
    assert s["keys"]["openai"] == masked          # ключ не изменился
    assert s["has_keys"]["openai"] is True


def test_cross_check_settings_default_and_persist():
    s = client.get("/api/settings").json()
    assert "cross_check_enabled" in s and "cross_check_provider" in s
    client.put("/api/settings", json={"cross_check_enabled": True, "cross_check_provider": "openai"})
    s2 = client.get("/api/settings").json()
    assert s2["cross_check_enabled"] is True
    assert s2["cross_check_provider"] == "openai"


def test_test_connection_demo_returns_not_ok():
    r = client.post("/api/settings/test", json={"provider": "demo"}).json()
    assert r["ok"] is False


def test_settings_writes_and_prompts_require_auth():
    anon = TestClient(app)   # без заголовка авторизации
    # GET настроек открыт (маскированный) — нужен чату/навбару:
    assert anon.get("/api/settings").status_code == 200
    # запись настроек и промпты — закрыты:
    assert anon.put("/api/settings", json={"provider": "demo"}).status_code == 401
    assert anon.post("/api/settings/test", json={"provider": "demo"}).status_code == 401
    assert anon.get("/api/prompts").status_code == 401
    assert anon.put("/api/prompts/x", json={"body": "y"}).status_code == 401
