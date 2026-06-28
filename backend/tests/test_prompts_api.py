from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_list_prompts():
    rows = client.get("/api/prompts").json()
    keys = {r["key"] for r in rows}
    assert {"norm_extraction", "estimate_edit"} <= keys


def test_edit_then_reset_prompt():
    client.put("/api/prompts/estimate_edit", json={"body": "МОЙ КАСТОМНЫЙ ПРОМПТ"})
    after = {r["key"]: r for r in client.get("/api/prompts").json()}["estimate_edit"]
    assert after["body"] == "МОЙ КАСТОМНЫЙ ПРОМПТ"
    assert after["is_custom"] is True

    client.post("/api/prompts/estimate_edit/reset")
    reset = {r["key"]: r for r in client.get("/api/prompts").json()}["estimate_edit"]
    assert reset["is_custom"] is False
    assert reset["body"] != "МОЙ КАСТОМНЫЙ ПРОМПТ"


def test_edit_unknown_prompt_404():
    assert client.put("/api/prompts/nope", json={"body": "x"}).status_code == 404
