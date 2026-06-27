"""Effective runtime settings: .env defaults overlaid with DB AppSetting rows."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AppSetting

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


test_provider.__test__ = False
