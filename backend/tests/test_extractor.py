"""Тесты LLM-извлечения норм (регрессия: документы — ORM-объекты, не кортежи)."""
from __future__ import annotations

import json

from app.llm.base import LLMProvider, LLMResult
from app.norms import extractor
from app.norms.resolver import ensure_documents
from app.schemas import BuildingInput


def _input(**kw) -> BuildingInput:
    base = dict(object_type="Жилой дом", demo_mode=False, use_search=True)
    base.update(kw)
    return BuildingInput(**base)


class _FakeProvider(LLMProvider):
    name = "fake"
    available = True

    def __init__(self, payload: dict, sources: list[dict] | None = None):
        self._payload = payload
        self._sources = sources or []

    def complete(self, system, user, *, use_search=False, temperature=0.15):
        # сохраняем переданный user-промпт для проверок
        self.last_user = user
        return LLMResult(text=json.dumps(self._payload), sources=self._sources)


def test_build_user_prompt_accepts_norm_documents(db):
    """build_user_prompt должен принимать NormDocument-объекты (атрибуты, не индексы)."""
    docs = ensure_documents(db, "Жилой дом")
    assert docs, "должны быть засеяны документы для жилого дома"
    prompt = extractor.build_user_prompt(_input(), docs)
    # код, заголовок и url первого документа попали в промпт
    d = docs[0]
    assert d.code in prompt
    assert d.title in prompt
    assert d.url in prompt


def test_extract_params_runs_with_documents(db, monkeypatch):
    """Полный путь извлечения с реальными NormDocument не падает (регрессия
    TypeError: 'NormDocument' object is not subscriptable)."""
    payload = {
        "params": [
            {"category": "frame_concrete_per_area", "value": 0.42, "unit": "м3/м2",
             "document_code": "СН РК 3.02-01-2023", "confidence": 0.7,
             "needs_review": False, "note": "ок"},
        ],
        "sources": [{"code": "СН РК 3.02-01-2023", "title": "Жилые", "confirmed": True}],
    }
    fake = _FakeProvider(payload, sources=[{"url": "https://example.kz", "title": "web"}])
    monkeypatch.setattr(extractor, "get_provider", lambda: fake)

    docs = ensure_documents(db, "Жилой дом")
    params, sources, web_links = extractor.extract_params(db, _input(), docs)

    assert "frame_concrete_per_area" in params
    assert params["frame_concrete_per_area"].source == "llm"
    assert any(s.get("confirmed") for s in sources)
    assert web_links and web_links[0]["url"] == "https://example.kz"
    # промпт собран из документов реестра
    assert docs[0].code in fake.last_user
