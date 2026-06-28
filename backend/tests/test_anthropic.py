"""Регрессия: запрос к Anthropic не содержит `temperature` (новые модели его
отвергают — "`temperature` is deprecated for this model")."""
import app.llm.anthropic as anth
from app.llm.anthropic import AnthropicProvider


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"content": [{"type": "text", "text": "ok"}]}


def test_anthropic_request_omits_temperature(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        return _Resp()

    monkeypatch.setattr(anth.httpx, "post", fake_post)
    provider = AnthropicProvider(api_key="x", model="claude-opus-4-8")
    result = provider.complete("система", "вопрос")

    assert result.text == "ok"
    assert "temperature" not in captured["body"]
    assert captured["body"]["model"] == "claude-opus-4-8"
    assert captured["body"]["max_tokens"] == 4096
