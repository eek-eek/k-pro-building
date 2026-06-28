# Ансамбль LLM (кросс-проверка норм) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить opt-in ансамбль: второй провайдер (OpenAI) независимо извлекает нормы, результаты сравниваются по категориям; согласие → `confidence↑`, расхождение → `needs_review` + оба значения. Ресурсный расчёт не меняется; по умолчанию выключено.

**Architecture:** Настройки (тумблер + проверяющий провайдер) → `factory.build_named_provider` поднимает второй провайдер → `extractor.cross_check_params` независимо извлекает и сравнивает → аннотирует LLM-параметры → `resolver._build_profile` встраивает результат в `NormProfile.cross_check` (+ инвалидация кэша при включённом тумблере) → `build_estimate` пишет сводку в `warnings`.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0, Pydantic v2, pytest; ванильный фронт. Спека: `docs/superpowers/specs/2026-06-28-llm-ensemble-cross-check-design.md`.

**Константы:** `REL_TOL=0.15`, `ABS_FLOOR=1e-3`, `CONF_BONUS=0.15`, `NOTE_MAX=500`.

---

### Task 1: Настройки кросс-проверки (config + service + API)

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/settings_service.py`
- Modify: `backend/app/schemas.py` (`SettingsUpdate`)
- Modify: `backend/app/api/routes.py` (GET/PUT /settings)
- Test: `backend/tests/test_settings_api.py`

- [ ] **Step 1: Падающий тест**

Добавить в `backend/tests/test_settings_api.py`:
```python
def test_cross_check_settings_default_and_persist():
    s = client.get("/api/settings").json()
    assert "cross_check_enabled" in s and "cross_check_provider" in s
    client.put("/api/settings", json={"cross_check_enabled": True, "cross_check_provider": "openai"})
    s2 = client.get("/api/settings").json()
    assert s2["cross_check_enabled"] is True
    assert s2["cross_check_provider"] == "openai"
```

- [ ] **Step 2: Запустить — упадёт**

Run: `cd backend && .venv/bin/python -m pytest tests/test_settings_api.py::test_cross_check_settings_default_and_persist -q`
Expected: FAIL (`KeyError`/нет ключей).

- [ ] **Step 3: config.py — два новых поля**

В `backend/app/config.py` в классе `Settings`, после `openai_model: str = "gpt-4o"` добавить:
```python
    cross_check_enabled: bool = False
    cross_check_provider: str = "openai"  # проверяющий провайдер (ансамбль)
```

- [ ] **Step 4: settings_service.py — ключи, dataclass, резолв**

В `backend/app/settings_service.py`:
- `SETTING_KEYS` — добавить элементы:
```python
SETTING_KEYS = (
    "llm_provider", "gemini_api_key", "anthropic_api_key", "openai_api_key",
    "gemini_model", "anthropic_model", "openai_model", "llm_use_search",
    "cross_check_enabled", "cross_check_provider",
)
```
- `_BOOL_KEYS`:
```python
_BOOL_KEYS = {"llm_use_search", "cross_check_enabled"}
```
- В `@dataclass EffectiveSettings` добавить ПОСЛЕ `llm_use_search: bool` (поля с дефолтами идут последними):
```python
    cross_check_enabled: bool = False
    cross_check_provider: str = "openai"
```
- В `get_effective_settings`, в конструктор `EffectiveSettings(...)` добавить:
```python
        cross_check_enabled=_as_bool(pick("cross_check_enabled")),
        cross_check_provider=pick("cross_check_provider"),
```
(Второй конструктор `EffectiveSettings(...)` в `test_provider` НЕ трогаем — новые поля имеют дефолты.)

- [ ] **Step 5: schemas.SettingsUpdate — два Optional-поля**

В `backend/app/schemas.py` в классе `SettingsUpdate` добавить:
```python
    cross_check_enabled: Optional[bool] = None
    cross_check_provider: Optional[str] = None
```

- [ ] **Step 6: routes.py — GET отдаёт, PUT сохраняет**

В `backend/app/api/routes.py`:
- В `get_settings_api`, в возвращаемый dict (рядом с `"use_search"`) добавить:
```python
        "cross_check_enabled": eff.cross_check_enabled,
        "cross_check_provider": eff.cross_check_provider,
```
- В `put_settings_api`, перед `save_settings(db, updates)` добавить:
```python
    if body.cross_check_enabled is not None:
        updates["cross_check_enabled"] = body.cross_check_enabled
    if body.cross_check_provider is not None:
        updates["cross_check_provider"] = body.cross_check_provider
```

- [ ] **Step 7: Тест зелёный + полный сьют**

Run: `cd backend && .venv/bin/python -m pytest tests/test_settings_api.py -q`
Expected: PASS (все settings-тесты).
Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: всё зелёное (132 → 133).

- [ ] **Step 8: Commit**

```bash
git add backend/app/config.py backend/app/settings_service.py backend/app/schemas.py backend/app/api/routes.py backend/tests/test_settings_api.py
git commit -m "feat(ensemble): настройки кросс-проверки (тумблер + проверяющий провайдер)"
```

---

### Task 2: `build_named_provider` в фабрике

**Files:**
- Modify: `backend/app/llm/factory.py`
- Test: `backend/tests/test_factory.py` (создать)

- [ ] **Step 1: Падающий тест**

Create `backend/tests/test_factory.py`:
```python
"""Фабрика провайдеров: сборка по явному имени."""
from __future__ import annotations

from app.llm.factory import build_named_provider, build_provider
from app.settings_service import EffectiveSettings


def _eff(provider="anthropic"):
    return EffectiveSettings(
        llm_provider=provider, gemini_api_key="g", anthropic_api_key="a",
        openai_api_key="o", gemini_model="gemini-2.5-flash",
        anthropic_model="claude-opus-4-8", openai_model="gpt-4o",
        llm_use_search=False,
    )


def test_build_named_provider_by_name():
    assert build_named_provider(_eff(), "openai").name == "openai"
    assert build_named_provider(_eff(), "anthropic").name == "anthropic"
    assert build_named_provider(_eff(), "gemini").name == "gemini"
    assert build_named_provider(_eff(), "demo").name == "demo"


def test_build_provider_delegates():
    # build_provider строит провайдера активного llm_provider
    assert build_provider(_eff("openai")).name == "openai"
```

- [ ] **Step 2: Запустить — упадёт**

Run: `cd backend && .venv/bin/python -m pytest tests/test_factory.py -q`
Expected: FAIL (`ImportError: build_named_provider`).

- [ ] **Step 3: Реализовать**

Заменить тело `backend/app/llm/factory.py` (функции `build_provider`):
```python
def build_named_provider(eff, name: str) -> LLMProvider:
    """Построить провайдера по ЯВНОМУ имени из per-provider ключей/моделей eff."""
    name = (name or "demo").lower()
    if name == "gemini":
        return GeminiProvider(eff.gemini_api_key, eff.gemini_model, eff.llm_use_search)
    if name == "anthropic":
        return AnthropicProvider(eff.anthropic_api_key, eff.anthropic_model)
    if name == "openai":
        return OpenAIProvider(eff.openai_api_key, eff.openai_model)
    return DemoProvider()


def build_provider(eff) -> LLMProvider:
    return build_named_provider(eff, eff.llm_provider)
```
(`get_provider()` остаётся как есть — вызывает `build_provider`.)

- [ ] **Step 4: Тест зелёный**

Run: `cd backend && .venv/bin/python -m pytest tests/test_factory.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/factory.py backend/tests/test_factory.py
git commit -m "feat(ensemble): build_named_provider — сборка провайдера по имени"
```

---

### Task 3: `_parse_params` + отбраковка невалидных значений

**Files:**
- Modify: `backend/app/norms/extractor.py`
- Test: `backend/tests/test_extractor.py` (создать)

- [ ] **Step 1: Падающий тест**

Create `backend/tests/test_extractor.py`:
```python
"""Разбор LLM-ответа в нормы: валидация значений."""
from __future__ import annotations

from app.norms.extractor import _parse_params


def test_parse_valid_params():
    data = {"params": [
        {"category": "rebar_kg_per_m3", "value": 95, "unit": "кг/м³", "confidence": 0.7},
    ]}
    params = _parse_params(data)
    assert "rebar_kg_per_m3" in params
    assert params["rebar_kg_per_m3"].value == 95
    assert params["rebar_kg_per_m3"].source == "llm"


def test_parse_skips_unknown_category_and_bad_values():
    data = {"params": [
        {"category": "НЕТ_ТАКОЙ", "value": 1},
        {"category": "rebar_kg_per_m3", "value": -5},        # отрицательное → skip
        {"category": "frame_concrete_per_area", "value": "abc"},  # не число → skip
    ]}
    params = _parse_params(data)
    assert params == {}


def test_parse_empty():
    assert _parse_params({}) == {}
```

- [ ] **Step 2: Запустить — упадёт**

Run: `cd backend && .venv/bin/python -m pytest tests/test_extractor.py -q`
Expected: FAIL (`ImportError: _parse_params`).

- [ ] **Step 3: Вынести `_parse_params` + добавить валидацию**

В `backend/app/norms/extractor.py`:
- В шапку добавить `import math` (рядом с `import json`).
- Добавить функцию (например, перед `extract_params`):
```python
def _parse_params(data: dict) -> dict[str, NormParam]:
    """Разобрать data['params'] в нормы. Отбрасывает неизвестные категории и
    невалидные значения (нечисловые/нечисловые-конечные/отрицательные)."""
    params: dict[str, NormParam] = {}
    for raw in data.get("params", []) or []:
        cat = raw.get("category")
        if cat not in CATEGORY_META:
            continue
        try:
            value = float(raw.get("value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        unit, _ = CATEGORY_META[cat]
        params[cat] = NormParam(
            category=cat,
            value=value,
            unit=raw.get("unit") or unit,
            source="llm",
            confidence=float(raw.get("confidence", 0.6) or 0.6),
            document_code=raw.get("document_code"),
            note=(raw.get("note") or "")[:500],
            needs_review=bool(raw.get("needs_review", False)),
        )
    return params
```
- В `extract_params` заменить блок разбора (цикл `for raw in data.get("params", ...)` целиком) на:
```python
    data, web_links = provider.extract_json(
        system, user, use_search=inp.use_search
    )
    params = _parse_params(data)
    sources = data.get("sources", []) or []
    return params, sources, web_links
```

- [ ] **Step 4: Тест зелёный + полный сьют (нет регрессии извлечения)**

Run: `cd backend && .venv/bin/python -m pytest tests/test_extractor.py -q`
Expected: PASS (3 passed).
Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: всё зелёное (поведение основного извлечения не изменилось — только вынос + отбраковка явного мусора).

- [ ] **Step 5: Commit**

```bash
git add backend/app/norms/extractor.py backend/tests/test_extractor.py
git commit -m "feat(ensemble): _parse_params (общий разбор) + отбраковка отрицательных/нечисловых"
```

---

### Task 4: Схема `CrossCheck` + `cross_check_params`

**Files:**
- Modify: `backend/app/schemas.py` (`CrossCheck` + `NormProfile.cross_check`)
- Modify: `backend/app/norms/extractor.py` (`cross_check_params` + хелперы + константы)
- Test: `backend/tests/test_cross_check.py` (создать)

- [ ] **Step 1: Падающий тест (с fake-проверяющим)**

Create `backend/tests/test_cross_check.py`:
```python
"""Кросс-проверка норм вторым провайдером (через monkeypatch фабрики)."""
from __future__ import annotations

import app.llm.factory as factory
from app.norms.extractor import cross_check_params
from app.schemas import NormParam
from app.settings_service import save_settings


class _Fake:
    name = "openai"
    available = True
    def __init__(self, params):
        self._params = params
    def extract_json(self, system, user, *, use_search=False):
        return {"params": self._params}, []


def _enable(db, provider="openai"):
    save_settings(db, {"llm_provider": "anthropic",
                       "cross_check_enabled": True, "cross_check_provider": provider})


def _primary():
    return {"rebar_kg_per_m3": NormParam(category="rebar_kg_per_m3", value=100,
                                         unit="кг/м³", source="llm", confidence=0.6)}


def test_agreement_bumps_confidence(db, monkeypatch):
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([{"category": "rebar_kg_per_m3", "value": 105, "unit": "кг/м³"}]))
    params, cc = cross_check_params(db, _inp(), [], _primary())
    assert cc.ran is True and cc.agreed == 1 and cc.disputed == 0
    assert params["rebar_kg_per_m3"].confidence > 0.6
    assert "подтверждено" in params["rebar_kg_per_m3"].note


def test_disagreement_flags_review(db, monkeypatch):
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([{"category": "rebar_kg_per_m3", "value": 200, "unit": "кг/м³"}]))
    params, cc = cross_check_params(db, _inp(), [], _primary())
    assert cc.disputed == 1
    assert params["rebar_kg_per_m3"].needs_review is True
    assert "расхождение" in params["rebar_kg_per_m3"].note


def test_both_zero_is_agreement(db, monkeypatch):
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([{"category": "finishing_factor", "value": 0, "unit": "коэф."}]))
    prim = {"finishing_factor": NormParam(category="finishing_factor", value=0.0,
                                          unit="коэф.", source="llm", confidence=0.6)}
    params, cc = cross_check_params(db, _inp(), [], prim)
    assert cc.agreed == 1 and cc.disputed == 0  # 0 vs 0 — согласие, не астрономический rel


def test_disabled_returns_untouched(db, monkeypatch):
    save_settings(db, {"cross_check_enabled": False})
    called = {"n": 0}
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: called.__setitem__("n", called["n"] + 1) or _Fake([]))
    params, cc = cross_check_params(db, _inp(), [], _primary())
    assert cc.enabled is False and cc.ran is False
    assert called["n"] == 0  # проверяющий не строился


def test_empty_primary_no_second_call(db, monkeypatch):
    _enable(db)
    called = {"n": 0}
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: called.__setitem__("n", called["n"] + 1) or _Fake([]))
    params, cc = cross_check_params(db, _inp(), [], {})
    assert cc.ran is False and called["n"] == 0  # пустой основной → без 2-го вызова


def test_unreadable_verifier_degrades(db, monkeypatch):
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([]))  # вернул 0 параметров
    params, cc = cross_check_params(db, _inp(), [], _primary())
    assert cc.ran is False and "нечитаемый" in cc.reason
    assert "не дала значение" not in params["rebar_kg_per_m3"].note  # без ложного missing


def _inp():
    from app.schemas import BuildingInput
    return BuildingInput(object_type="Жилой дом")
```

- [ ] **Step 2: Запустить — упадёт**

Run: `cd backend && .venv/bin/python -m pytest tests/test_cross_check.py -q`
Expected: FAIL (`ImportError: cross_check_params` / нет `CrossCheck`).

- [ ] **Step 3: Схема `CrossCheck` + поле в `NormProfile`**

В `backend/app/schemas.py` ПЕРЕД `class NormProfile(BaseModel):` добавить:
```python
class CrossCheck(BaseModel):
    """Итог кросс-проверки норм вторым ИИ (ансамбль)."""

    enabled: bool = False
    ran: bool = False
    verifier: str = ""
    agreed: int = 0
    disputed: int = 0
    missing: int = 0
    extra: int = 0
    extra_keys: list[str] = Field(default_factory=list)
    reason: str = ""
```
И в `class NormProfile(BaseModel):` добавить поле (например, после `from_cache`):
```python
    cross_check: Optional["CrossCheck"] = None
```

- [ ] **Step 4: `cross_check_params` + хелперы в `extractor.py`**

В `backend/app/norms/extractor.py` добавить константы (рядом с верхом модуля, после импортов):
```python
REL_TOL = 0.15
ABS_FLOOR = 1e-3
CONF_BONUS = 0.15
NOTE_MAX = 500
```
И функции (в конец файла):
```python
def _cap_note(s: str) -> str:
    return s[:NOTE_MAX]


def _pct(rel: float) -> str:
    return f"{min(rel, 9.99):.0%}"


def cross_check_params(db, inp: BuildingInput, documents, primary_params):
    """Независимо извлечь нормы проверяющим провайдером и сверить с primary_params.

    Аннотирует primary_params (confidence/needs_review/note) НА МЕСТЕ и возвращает
    (primary_params, CrossCheck). Мягкая деградация на всех путях отказа.
    """
    from ..schemas import CrossCheck
    from ..settings_service import get_effective_settings
    from ..llm.factory import build_named_provider
    from ..prompts import get_prompt

    eff = get_effective_settings(db)
    if not primary_params:
        return primary_params, CrossCheck(enabled=eff.cross_check_enabled, ran=False,
                                          reason="основное LLM-извлечение пусто")
    if not eff.cross_check_enabled:
        return primary_params, CrossCheck(enabled=False)
    if eff.cross_check_provider == eff.llm_provider:
        return primary_params, CrossCheck(enabled=True, ran=False,
                                          reason="проверяющий совпадает с основным")
    verifier = build_named_provider(eff, eff.cross_check_provider)
    if not verifier.available:
        return primary_params, CrossCheck(enabled=True, ran=False,
                                          reason="проверяющий недоступен (нет ключа)")

    user = build_user_prompt(inp, documents)
    system = get_prompt(db, "norm_extraction") or SYSTEM_PROMPT
    try:
        data, _ = verifier.extract_json(system, user, use_search=eff.llm_use_search)
    except LLMUnavailable:
        return primary_params, CrossCheck(enabled=True, ran=False,
                                          reason="ошибка проверяющего")
    verifier_params = _parse_params(data)
    if not verifier_params:
        return primary_params, CrossCheck(enabled=True, ran=False,
                                          reason="проверяющий вернул нечитаемый ответ")

    agreed = disputed = missing = 0
    extra_keys = [c for c in verifier_params if c not in primary_params]
    for cat, p in primary_params.items():
        v = verifier_params.get(cat)
        if v is None:
            missing += 1
            p.note = _cap_note(p.note + " · вторая модель не дала значение")
            continue
        if p.unit and v.unit and p.unit != v.unit:
            p.needs_review = True
            p.note = _cap_note(p.note + f" · ⚠ единицы расходятся: {p.unit} vs {v.unit}")
            disputed += 1
            continue
        denom = max(abs(p.value), abs(v.value), ABS_FLOOR)
        rel = abs(p.value - v.value) / denom
        if rel <= REL_TOL:
            p.confidence = min(1.0, p.confidence + CONF_BONUS)
            p.note = _cap_note(p.note + f" · ✓ подтверждено {verifier.name}")
            agreed += 1
        else:
            p.needs_review = True
            p.note = _cap_note(
                p.note + f" · ⚠ расхождение с {verifier.name}: {p.value} vs {v.value} ({_pct(rel)})"
            )
            disputed += 1
    return primary_params, CrossCheck(
        enabled=True, ran=True, verifier=eff.cross_check_provider,
        agreed=agreed, disputed=disputed, missing=missing,
        extra=len(extra_keys), extra_keys=extra_keys[:10],
    )
```

- [ ] **Step 5: Тест зелёный**

Run: `cd backend && .venv/bin/python -m pytest tests/test_cross_check.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/norms/extractor.py backend/tests/test_cross_check.py
git commit -m "feat(ensemble): CrossCheck + cross_check_params (сравнение, деградация, краевые случаи)"
```

---

### Task 5: Интеграция в резолвер + инвалидация кэша

**Files:**
- Modify: `backend/app/norms/resolver.py`
- Test: `backend/tests/test_cross_check.py` (дополнить)

- [ ] **Step 1: Падающий тест интеграции**

Добавить в `backend/tests/test_cross_check.py`:
```python
def test_resolver_attaches_cross_check(db, monkeypatch):
    import app.llm.factory as factory
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput
    # основной провайдер — demo? Нет: cross_check_params строит ТОЛЬКО проверяющего.
    # Извлечение основного идёт через get_provider(); чтобы был непустой llm_params,
    # подменим extract_params на детерминированный набор.
    import app.norms.extractor as extractor
    monkeypatch.setattr(extractor, "extract_params",
                        lambda db_, inp_, docs_: (
                            {"rebar_kg_per_m3": __import__("app.schemas", fromlist=["NormParam"]).NormParam(
                                category="rebar_kg_per_m3", value=100, unit="кг/м³", source="llm", confidence=0.6)},
                            [], []))
    _enable(db)
    monkeypatch.setattr(factory, "build_named_provider",
                        lambda eff, name: _Fake([{"category": "rebar_kg_per_m3", "value": 105, "unit": "кг/м³"}]))
    inp = BuildingInput(object_type="Жилой дом", demo_mode=False, use_search=False)
    prof = resolve_norm_profile(db, inp, force=True)  # мимо кэша
    assert prof.cross_check is not None
    assert prof.cross_check.ran is True
    assert prof.cross_check.agreed >= 1
```

- [ ] **Step 2: Запустить — упадёт**

Run: `cd backend && .venv/bin/python -m pytest tests/test_cross_check.py::test_resolver_attaches_cross_check -q`
Expected: FAIL (`prof.cross_check is None`).

- [ ] **Step 3: Импорт + интеграция в `_build_profile`**

В `backend/app/norms/resolver.py`:
- В импорт схем добавить `CrossCheck`:
```python
from ..schemas import BuildingInput, CrossCheck, NormParam, NormProfile, NormSource
```
- В `_build_profile`, ПЕРЕД блоком `if not inp.demo_mode:` добавить инициализацию:
```python
    cc = CrossCheck(enabled=False)
```
- Внутри `try`, заменить блок (текущие строки извлечения+мёрджа+persist):
```python
            llm_params, llm_sources, web_links = extractor.extract_params(db, inp, documents)
            for cat, p in llm_params.items():
                params[cat] = _better(params.get(cat, p), p) if cat in params else p
            _persist_llm_rules(db, inp, llm_params, docs_by_code)
```
на:
```python
            llm_params, llm_sources, web_links = extractor.extract_params(db, inp, documents)
            llm_params, cc = extractor.cross_check_params(db, inp, documents, llm_params)
            for cat, p in llm_params.items():
                params[cat] = _better(params.get(cat, p), p) if cat in params else p
            _persist_llm_rules(db, inp, llm_params, docs_by_code)
```
- В создании профиля добавить аргумент:
```python
    profile = NormProfile(
        signature=signature,
        object_type=inp.object_type,
        params=params,
        sources=sources,
        from_cache=False,
        cross_check=cc,
    )
```

- [ ] **Step 4: Инвалидация кэша при включённом тумблере**

В `backend/app/norms/resolver.py`, перед `resolve_norm_profile` добавить хелпер:
```python
def _cache_usable(eff, cached: Optional[NormProfile]) -> bool:
    """Кэш годен, если он есть и (кросс-проверка выкл ИЛИ профиль уже проверен)."""
    if cached is None:
        return False
    if eff.cross_check_enabled and (cached.cross_check is None or not cached.cross_check.ran):
        return False
    return True
```
В `resolve_norm_profile` после `signature = inp.signature()` добавить чтение настроек:
```python
    from ..settings_service import get_effective_settings
    eff = get_effective_settings(db)
```
Заменить обе проверки кэша:
```python
    cached = _cache_get(db, signature)
    if cached is not None:
        progress("norms_cache", "Профиль найден в БД (без обращения к LLM)")
        return cached
```
на:
```python
    cached = _cache_get(db, signature)
    if _cache_usable(eff, cached):
        progress("norms_cache", "Профиль найден в БД (без обращения к LLM)")
        return cached
```
(оба места — быстрый путь и под `_lock_for`.)

- [ ] **Step 5: Тест зелёный + полный сьют**

Run: `cd backend && .venv/bin/python -m pytest tests/test_cross_check.py -q`
Expected: PASS (7 passed).
Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: всё зелёное (по умолчанию тумблер выкл → старые тесты резолвера не меняются; `cross_check` дефолт `enabled=False`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/norms/resolver.py backend/tests/test_cross_check.py
git commit -m "feat(ensemble): интеграция кросс-проверки в резолвер + инвалидация кэша при включённом тумблере"
```

---

### Task 6: Сводка кросс-проверки в смете

**Files:**
- Modify: `backend/app/calc/estimate.py`
- Test: `backend/tests/test_cross_check.py` (дополнить)

- [ ] **Step 1: Падающий тест**

Добавить в `backend/tests/test_cross_check.py`:
```python
def test_estimate_warning_from_cross_check(db):
    from app.calc import build_estimate
    from app.schemas import NormProfile, CrossCheck, BuildingInput
    inp = BuildingInput(demo_mode=True, use_search=False, object_type="Жилой дом")
    # профиль с заполненной кросс-проверкой
    from app.norms import resolve_norm_profile
    prof = resolve_norm_profile(db, inp)
    prof.cross_check = CrossCheck(enabled=True, ran=True, verifier="openai",
                                  agreed=3, disputed=1)
    r = build_estimate(db, inp, prof)
    assert any("кросс-проверку (openai)" in w.lower() for w in r.warnings)
```

- [ ] **Step 2: Запустить — упадёт**

Run: `cd backend && .venv/bin/python -m pytest tests/test_cross_check.py::test_estimate_warning_from_cross_check -q`
Expected: FAIL (нет такого warning).

- [ ] **Step 3: Добавить сводку в `build_estimate`**

В `backend/app/calc/estimate.py`, в блоке формирования `warnings`, сразу ПОСЛЕ ветки `if profile.from_cache: warnings.append(...)` добавить:
```python
    if profile.cross_check and profile.cross_check.ran:
        cc = profile.cross_check
        msg = (f"Профиль прошёл кросс-проверку ({cc.verifier}): "
               f"подтверждено {cc.agreed}, расхождений {cc.disputed}")
        if cc.missing:
            msg += f", без ответа {cc.missing}"
        if cc.extra_keys:
            msg += f"; вторая модель дополнительно предложила: {', '.join(cc.extra_keys)}"
        warnings.append(msg + ".")
    elif (profile.cross_check and profile.cross_check.enabled
          and not profile.cross_check.ran and profile.cross_check.reason):
        warnings.append(f"Кросс-проверка включена, но не выполнена: {profile.cross_check.reason}.")
```

- [ ] **Step 4: Тест зелёный + полный сьют**

Run: `cd backend && .venv/bin/python -m pytest tests/test_cross_check.py -q`
Expected: PASS (8 passed).
Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: всё зелёное (~140).

- [ ] **Step 5: Commit**

```bash
git add backend/app/calc/estimate.py backend/tests/test_cross_check.py
git commit -m "feat(ensemble): сводка кросс-проверки в warnings сметы (честна на кэш-хите)"
```

---

### Task 7: Фронт — тумблер и выбор проверяющего в Настройках

**Files:**
- Modify: `frontend/app.js` (`viewSettings`, `Api.putSettings` уже шлёт body)

- [ ] **Step 1: Добавить чекбокс + select в форму Настроек**

В `frontend/app.js`, в `viewSettings`, в блоке провайдера (после `<div class="checks">…useSearch…</div>`) добавить разметку:
```javascript
        <div class="checks"><label><input type="checkbox" id="crossCheck" ${s.cross_check_enabled ? "checked" : ""}> Кросс-проверка норм вторым ИИ (ансамбль) — дороже: 2 вызова</label></div>
        <div class="field"><label>Проверяющий провайдер</label>
          <select id="crossProvider">${["gemini","anthropic","openai"].map((p) =>
            `<option value="${p}" ${p === s.cross_check_provider ? "selected" : ""}>${p}</option>`).join("")}</select>
          <div class="hint">Должен отличаться от основного, иначе проверка не выполнится.</div></div>
```
(Вставить внутри `<div class="card">` блока провайдера, до `<div class="row-actions">`.)

- [ ] **Step 2: Отправлять новые поля при сохранении**

В обработчике `saveSettings` (внутри `viewSettings`), в объект `body` добавить:
```javascript
      cross_check_enabled: document.getElementById("crossCheck").checked,
      cross_check_provider: document.getElementById("crossProvider").value || undefined,
```

- [ ] **Step 3: Синтаксис-проверка**

Run: `node --check frontend/app.js && echo OK`
Expected: `OK`.

- [ ] **Step 4: Live-смоук (опционально, demo-сервер)**

```bash
cd backend && lsof -ti tcp:8000 | xargs kill -9 2>/dev/null; \
LLM_PROVIDER=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning &
sleep 3
AUTH=$(python3 -c 'import base64;print("Basic "+base64.b64encode(b"admin:admin12345").decode())')
curl -s -X PUT http://127.0.0.1:8000/api/settings -H "Authorization: $AUTH" -H 'Content-Type: application/json' \
  -d '{"cross_check_enabled":true,"cross_check_provider":"openai"}' >/dev/null
curl -s http://127.0.0.1:8000/api/settings | python3 -c 'import sys,json;s=json.load(sys.stdin);print("cross_check:",s.get("cross_check_enabled"),s.get("cross_check_provider"))'
lsof -ti tcp:8000 | xargs kill -9 2>/dev/null
```
Expected: `cross_check: True openai`.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js
git commit -m "feat(ensemble): тумблер кросс-проверки и выбор проверяющего в Настройках"
```

---

## Self-Review

**1. Spec coverage:** настройки (T1), build_named_provider (T2), _parse_params+валидация (T3), CrossCheck+cross_check_params со всеми краевыми случаями (T4), резолвер+инвалидация кэша (T5), сводка в смете (T6), фронт (T7). Отложенное v2 (нормировка единиц, судья, чат) — вне плана. ✓

**2. Placeholder scan:** код полный в каждом шаге; команды с ожиданиями. ✓

**3. Type consistency:** `cross_check_params(db, inp, documents, primary_params) -> (dict, CrossCheck)`; `CrossCheck` поля совпадают в schemas/extractor/estimate/тестах; `NormProfile.cross_check: Optional[CrossCheck]`; `build_named_provider(eff, name)` зовётся в cross_check_params; `_parse_params` используется и в extract_params, и в cross_check. ✓

**4. Краевые случаи (из состязательного ревью спеки):** p==0 (ABS_FLOOR), единицы (см vs м), отрицательные (_parse_params), лимит ноты 500 (_cap_note), пустой основной (ранний выход, без 2-го вызова), нечитаемый JSON проверяющего (ran=False, без ложного missing), demo/== основной (ran=False), кэш-инвалидация при включённом тумблере, сводка past-tense (честна на кэш-хите). ✓

**5. Риски:** монкипатч `factory.build_named_provider` (локальный импорт в cross_check_params резолвит атрибут модуля при вызове → патч работает). EffectiveSettings — новые поля с дефолтами (второй конструктор в test_provider не ломается). Реордеринг extract→cross_check→merge→persist: _persist пишет аннотированные (cross-checked) правила; нота уже ≤500.

## Execution Handoff

План: `docs/superpowers/plans/2026-06-28-llm-ensemble-plan.md`. 7 задач. Рекомендация по исполнению — субагент-драйв (как 1A), либо инлайн для механических T1–T3.
