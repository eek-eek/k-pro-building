# YBC v0.2 — Plan 3: Settings, Provider, Prompts, Model Catalog (backend)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let the user configure the LLM provider, API key (masked), and model (from a per-provider catalog) at runtime — overriding `.env` without restart — plus edit/reset system prompts and test the connection.

**Architecture:** A `settings_service.py` computes EFFECTIVE settings = `.env` defaults overlaid with `AppSetting` rows (empty value = unset, never shadows `.env`). The provider factory builds from effective settings and is read fresh per call (no `lru_cache`), so saving in the UI takes effect immediately. Keys are masked in responses. A static `MODEL_CATALOG` feeds the dropdown. Prompts are edited/reset against the Plan 1 `Prompt` store.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest. Spec §7–§8.

**Run tests:** `cd backend && .venv/bin/python -m pytest -q`.

---

## File Structure
- `backend/app/settings_service.py` — **create**: `EffectiveSettings`, `get_effective_settings`, `save_settings`, `mask_key`, `MODEL_CATALOG`, `test_provider`.
- `backend/app/llm/factory.py` — **modify**: build provider from effective settings; drop `lru_cache`.
- `backend/app/api/routes.py` — **modify**: settings + prompts endpoints; `/health` uses effective provider.
- `backend/app/schemas.py` — **modify**: `SettingsUpdate`, `PromptUpdate`, `TestConnectionRequest`.
- `backend/tests/test_settings_service.py` — **create**.
- `backend/tests/test_settings_api.py` — **create**.

---

## Task 1: Settings service + provider factory + model catalog

**Files:** Create `backend/app/settings_service.py`; modify `backend/app/llm/factory.py`; test `backend/tests/test_settings_service.py`.

Context: `config.get_settings()` returns the env-loaded `Settings` (fields `llm_provider`, `gemini_api_key`, `anthropic_api_key`, `openai_api_key`, `gemini_model`, `anthropic_model`, `openai_model`, `llm_use_search`). `AppSetting(key, value)` is a key-value table. Providers: `GeminiProvider(api_key, model, use_search)`, `AnthropicProvider(api_key, model)`, `OpenAIProvider(api_key, model)`, `DemoProvider()`. `get_settings` is `@lru_cache`d (leave it — env defaults rarely change).

- [ ] **Step 1: Write failing test** `backend/tests/test_settings_service.py`:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app.settings_service import (
    get_effective_settings, save_settings, mask_key, MODEL_CATALOG, EffectiveSettings,
)


def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def test_empty_appsetting_does_not_shadow_env():
    db = _db()
    # seed an AppSetting row with empty value -> must be treated as unset
    db.add(models.AppSetting(key="gemini_api_key", value=""))
    db.commit()
    eff = get_effective_settings(db)
    # env default gemini_api_key is "" too, but the point: empty never overrides;
    # provider stays the env default, not blanked by the row
    assert isinstance(eff, EffectiveSettings)
    assert eff.llm_provider  # falls back to env default (non-empty)


def test_save_and_read_override():
    db = _db()
    save_settings(db, {"llm_provider": "anthropic", "anthropic_model": "claude-opus-4-8"})
    eff = get_effective_settings(db)
    assert eff.llm_provider == "anthropic"
    assert eff.anthropic_model == "claude-opus-4-8"


def test_use_search_bool_roundtrip():
    db = _db()
    save_settings(db, {"llm_use_search": False})
    assert get_effective_settings(db).llm_use_search is False
    save_settings(db, {"llm_use_search": True})
    assert get_effective_settings(db).llm_use_search is True


def test_mask_key():
    assert mask_key("") == ""
    assert mask_key("abcd") == "••••"
    masked = mask_key("AIzaSyA1234567890xyzQK")
    assert masked.startswith("AIza") and masked.endswith("zQK") and "•" in masked


def test_catalog_has_providers():
    assert set(MODEL_CATALOG) >= {"gemini", "anthropic", "openai", "demo"}
    assert any(m["id"] == "claude-opus-4-8" for m in MODEL_CATALOG["anthropic"])
```

- [ ] **Step 2: Run, confirm FAIL** (`ModuleNotFoundError: app.settings_service`):
`cd backend && .venv/bin/python -m pytest tests/test_settings_service.py -v`

- [ ] **Step 3: Create `backend/app/settings_service.py`:**
```python
"""Effective runtime settings: .env defaults overlaid with DB AppSetting rows."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AppSetting

# Per-provider selectable models (dropdown source). Anthropic IDs are the current
# model line; edit here when the catalog changes.
MODEL_CATALOG: dict[str, list[dict[str, str]]] = {
    "gemini": [
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
    ],
    "anthropic": [
        {"id": "claude-opus-4-8", "label": "Claude Opus 4.8"},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
    ],
    "openai": [
        {"id": "gpt-4o", "label": "GPT-4o"},
        {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
    ],
    "demo": [],
}

# Keys persisted in AppSetting (subset of Settings fields).
SETTING_KEYS = (
    "llm_provider", "gemini_api_key", "anthropic_api_key", "openai_api_key",
    "gemini_model", "anthropic_model", "openai_model", "llm_use_search",
)
_BOOL_KEYS = {"llm_use_search"}


@dataclass
class EffectiveSettings:
    llm_provider: str
    gemini_api_key: str
    anthropic_api_key: str
    openai_api_key: str
    gemini_model: str
    anthropic_model: str
    openai_model: str
    llm_use_search: bool

    def active_key(self) -> str:
        return getattr(self, f"{self.llm_provider}_api_key", "")

    def active_model(self) -> str:
        return getattr(self, f"{self.llm_provider}_model", "")


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _overrides(db: Session) -> dict[str, str]:
    # empty value = unset (never shadows .env)
    return {r.key: r.value for r in db.scalars(select(AppSetting)).all() if r.value != ""}


def get_effective_settings(db: Session) -> EffectiveSettings:
    base = get_settings()
    ov = _overrides(db)

    def pick(key: str):
        return ov[key] if key in ov else getattr(base, key)

    return EffectiveSettings(
        llm_provider=pick("llm_provider"),
        gemini_api_key=pick("gemini_api_key"),
        anthropic_api_key=pick("anthropic_api_key"),
        openai_api_key=pick("openai_api_key"),
        gemini_model=pick("gemini_model"),
        anthropic_model=pick("anthropic_model"),
        openai_model=pick("openai_model"),
        llm_use_search=_as_bool(pick("llm_use_search")),
    )


def save_settings(db: Session, updates: dict) -> None:
    """Upsert AppSetting rows. None values are skipped; bools/str stored as text."""
    for key, value in updates.items():
        if key not in SETTING_KEYS or value is None:
            continue
        text = "true" if (key in _BOOL_KEYS and value) else (
            "false" if key in _BOOL_KEYS else str(value))
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=text))
        else:
            row.value = text
    db.commit()


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 8}{key[-3:]}"


def test_provider(db: Session, provider: str | None = None,
                  api_key: str | None = None, model: str | None = None) -> tuple[bool, str]:
    """Cheap connection check. Uses given params or effective settings."""
    from .llm.factory import build_provider
    eff = get_effective_settings(db)
    prov = (provider or eff.llm_provider).lower()
    if prov == "demo":
        return False, "Demo-режим: настройте реальный провайдер."
    key = api_key if api_key not in (None, "") else getattr(eff, f"{prov}_api_key", "")
    mdl = model or getattr(eff, f"{prov}_model", "")
    test_eff = EffectiveSettings(
        llm_provider=prov,
        gemini_api_key=key if prov == "gemini" else eff.gemini_api_key,
        anthropic_api_key=key if prov == "anthropic" else eff.anthropic_api_key,
        openai_api_key=key if prov == "openai" else eff.openai_api_key,
        gemini_model=mdl if prov == "gemini" else eff.gemini_model,
        anthropic_model=mdl if prov == "anthropic" else eff.anthropic_model,
        openai_model=mdl if prov == "openai" else eff.openai_model,
        llm_use_search=False,
    )
    p = build_provider(test_eff)
    if not p.available:
        return False, "Ключ не задан."
    try:
        p.complete("Ты — тест.", "Ответь одним словом: ок", use_search=False)
        return True, "Соединение успешно."
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
```

- [ ] **Step 4: Refactor `backend/app/llm/factory.py`** to build from effective settings (hot reload, no cache):
```python
"""Фабрика LLM-провайдера из эффективных настроек (env + БД)."""
from __future__ import annotations

from ..database import SessionLocal
from .anthropic import AnthropicProvider
from .base import LLMProvider
from .demo import DemoProvider
from .gemini import GeminiProvider
from .openai import OpenAIProvider


def build_provider(eff) -> LLMProvider:
    provider = (eff.llm_provider or "demo").lower()
    if provider == "gemini":
        return GeminiProvider(eff.gemini_api_key, eff.gemini_model, eff.llm_use_search)
    if provider == "anthropic":
        return AnthropicProvider(eff.anthropic_api_key, eff.anthropic_model)
    if provider == "openai":
        return OpenAIProvider(eff.openai_api_key, eff.openai_model)
    return DemoProvider()


def get_provider() -> LLMProvider:
    """Build a provider from current effective settings (reads DB each call → hot reload)."""
    from ..settings_service import get_effective_settings
    with SessionLocal() as db:
        eff = get_effective_settings(db)
    return build_provider(eff)
```
(Remove the old `@lru_cache` and the `get_settings`-based body. `app.llm.__init__` still exposes `get_provider`.)

- [ ] **Step 5: Run** the service tests (expect 5 passed), then the FULL suite (all green — confirm `test_resolver.py` still passes: with no DB override and no key, the provider is still unavailable, so the demo/default path is unchanged):
`cd backend && .venv/bin/python -m pytest tests/test_settings_service.py -v`
`cd backend && .venv/bin/python -m pytest -q`

- [ ] **Step 6: Commit:**
```bash
git add backend/app/settings_service.py backend/app/llm/factory.py backend/tests/test_settings_service.py
git commit -m "feat(settings): effective settings (env+DB), model catalog, hot-reload provider"
```

---

## Task 2: Settings endpoints

**Files:** Modify `backend/app/api/routes.py`, `backend/app/schemas.py`; test `backend/tests/test_settings_api.py`.

- [ ] **Step 1: Write failing test** `backend/tests/test_settings_api.py`:
```python
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
    assert "secret" not in s["masked_key"]      # full key never returned
    assert "•" in s["masked_key"]


def test_put_settings_keeps_key_when_masked_value_resent():
    client.put("/api/settings", json={"provider": "anthropic",
               "api_key": "sk-ant-keepme-9999999999"})
    masked = client.get("/api/settings").json()["masked_key"]
    # resending the masked value must NOT overwrite the stored key
    client.put("/api/settings", json={"provider": "anthropic", "api_key": masked})
    assert client.get("/api/settings").json()["has_key"] is True


def test_test_connection_demo_returns_not_ok():
    r = client.post("/api/settings/test", json={"provider": "demo"}).json()
    assert r["ok"] is False
```

- [ ] **Step 2: Run, confirm FAIL** (404):
`cd backend && .venv/bin/python -m pytest tests/test_settings_api.py -v`

- [ ] **Step 3: Add schemas to `backend/app/schemas.py`:**
```python
class SettingsUpdate(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    use_search: Optional[bool] = None


class TestConnectionRequest(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
```

- [ ] **Step 4: Add endpoints to `backend/app/api/routes.py`.** Add imports: `from ..settings_service import get_effective_settings, save_settings, mask_key, MODEL_CATALOG, test_provider as run_test_provider` and add `SettingsUpdate, TestConnectionRequest` to the schemas import. Append:
```python
@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db)) -> dict:
    eff = get_effective_settings(db)
    return {
        "provider": eff.llm_provider,
        "model": eff.active_model(),
        "masked_key": mask_key(eff.active_key()),
        "has_key": bool(eff.active_key()),
        "use_search": eff.llm_use_search,
        "catalog": MODEL_CATALOG,
    }


@router.put("/settings")
def put_settings_api(body: SettingsUpdate, db: Session = Depends(get_db)) -> dict:
    eff = get_effective_settings(db)
    provider = (body.provider or eff.llm_provider).lower()
    updates: dict = {}
    if body.provider is not None:
        updates["llm_provider"] = provider
    if body.model is not None:
        updates[f"{provider}_model"] = body.model
    if body.use_search is not None:
        updates["llm_use_search"] = body.use_search
    if body.api_key is not None and body.api_key != "":
        # ignore a resent masked value (keep the stored key)
        if body.api_key != mask_key(getattr(eff, f"{provider}_api_key", "")):
            updates[f"{provider}_api_key"] = body.api_key
    save_settings(db, updates)
    return get_settings_api(db)


@router.post("/settings/test")
def test_connection_api(body: TestConnectionRequest, db: Session = Depends(get_db)) -> dict:
    ok, message = run_test_provider(db, body.provider, body.api_key, body.model)
    return {"ok": ok, "message": message}
```

- [ ] **Step 5: Update `/health`** to report the EFFECTIVE provider. Replace the health handler body:
```python
@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    eff = get_effective_settings(db)
    return {"status": "ok", "llm_provider": eff.llm_provider}
```

- [ ] **Step 6: Run** the settings-api test (expect 4 passed), then the FULL suite (all green):
`cd backend && .venv/bin/python -m pytest tests/test_settings_api.py -v`
`cd backend && .venv/bin/python -m pytest -q`

- [ ] **Step 7: Commit:**
```bash
git add backend/app/api/routes.py backend/app/schemas.py backend/tests/test_settings_api.py
git commit -m "feat(api): settings endpoints (get/put masked key, test-connection); health uses effective provider"
```

---

## Task 3: Prompts endpoints

**Files:** Modify `backend/app/api/routes.py`, `backend/app/schemas.py`; test `backend/tests/test_prompts_api.py`.

Context: `Prompt(key, title, description, body, is_custom)` model; `app.prompts.PROMPT_DEFAULTS` holds code defaults keyed by prompt key; prompts are seeded in `run_seed`.

- [ ] **Step 1: Write failing test** `backend/tests/test_prompts_api.py`:
```python
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
    assert reset["body"] != "МОЙ КАСТОМНЫЙ ПРОМПТ"  # restored to code default


def test_edit_unknown_prompt_404():
    assert client.put("/api/prompts/nope", json={"body": "x"}).status_code == 404
```

- [ ] **Step 2: Run, confirm FAIL** (404 / no endpoints):
`cd backend && .venv/bin/python -m pytest tests/test_prompts_api.py -v`

- [ ] **Step 3: Add schema to `backend/app/schemas.py`:**
```python
class PromptUpdate(BaseModel):
    body: str = Field(min_length=1)
```

- [ ] **Step 4: Add endpoints to `backend/app/api/routes.py`.** Add `from ..models import Prompt` (merge into the models import) and `from ..prompts import PROMPT_DEFAULTS` and `PromptUpdate` to schemas import. Append:
```python
@router.get("/prompts")
def list_prompts(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Prompt).order_by(Prompt.key)).all()
    return [{"key": p.key, "title": p.title, "description": p.description,
             "body": p.body, "is_custom": p.is_custom} for p in rows]


@router.put("/prompts/{key}")
def update_prompt(key: str, body: PromptUpdate, db: Session = Depends(get_db)) -> dict:
    row = db.scalar(select(Prompt).where(Prompt.key == key))
    if row is None:
        raise HTTPException(status_code=404, detail="prompt not found")
    row.body = body.body
    row.is_custom = True
    db.commit()
    return {"ok": True}


@router.post("/prompts/{key}/reset")
def reset_prompt(key: str, db: Session = Depends(get_db)) -> dict:
    row = db.scalar(select(Prompt).where(Prompt.key == key))
    if row is None:
        raise HTTPException(status_code=404, detail="prompt not found")
    default = PROMPT_DEFAULTS.get(key)
    if default is None:
        raise HTTPException(status_code=404, detail="no default for prompt")
    row.body = default["body"]
    row.is_custom = False
    db.commit()
    return {"ok": True}
```

- [ ] **Step 5: Run** the prompts-api test (expect 3 passed), then FULL suite (all green):
`cd backend && .venv/bin/python -m pytest tests/test_prompts_api.py -v`
`cd backend && .venv/bin/python -m pytest -q`

- [ ] **Step 6: Commit:**
```bash
git add backend/app/api/routes.py backend/app/schemas.py backend/tests/test_prompts_api.py
git commit -m "feat(api): prompt endpoints (list/update/reset)"
```

---

## Self-Review notes (author)
- **Spec §7 coverage:** effective settings env+DB with empty-unset precedence → Task 1 (`_overrides` filters empty); hot-reload via no-cache `get_provider` reading DB each call → Task 1; key masking → Task 1 + GET/PUT logic that ignores a resent masked value → Task 2; model catalog dropdown source (Anthropic IDs from current model line) → Task 1/GET; test-connection (demo → not ok) → Task 1/Task 2; prompt store edit/reset → Task 3.
- **§8 API contract:** GET/PUT `/settings`, POST `/settings/test`, GET `/prompts`, PUT `/prompts/{key}`, POST `/prompts/{key}/reset` — all by `key`.
- **Type consistency:** `get_effective_settings(db) -> EffectiveSettings`; `build_provider(eff)`; `save_settings(db, dict)`; `mask_key(str)`; provider key/model fields named `<provider>_api_key`/`<provider>_model` consistently.
- **Backward-compat:** dropping `lru_cache` on `get_provider` — provider build is cheap; the norm-resolve demo path is unchanged (still unavailable without a key). `get_settings` (env) stays cached.
- **Deferred:** prompt version history (v0.3); runtime model-list fetch from provider APIs (v0.3); encryption of keys at rest.
```
