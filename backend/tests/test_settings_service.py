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
    db.add(models.AppSetting(key="gemini_api_key", value=""))
    db.commit()
    eff = get_effective_settings(db)
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
