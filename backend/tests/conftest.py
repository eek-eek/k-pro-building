"""Общая настройка тестов: изолированная временная БД, demo-провайдер."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Тесты не должны ходить в сеть/LLM и трогать рабочую БД.
_TMP_DB = Path(tempfile.gettempdir()) / "ai_smeta_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["LLM_PROVIDER"] = "demo"

# backend/ в путь импорта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.seed import run_seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _seeded():
    run_seed()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_cross_check_settings():
    """Не давать настройкам протекать между тестами (общая сессия БД): иначе
    включённый где-то тумблер делал бы сьют зависимым от порядка сбора. Тарифы
    труда возвращаем к дефолту (вкл, индекс 1.0)."""
    yield
    from app.settings_service import save_settings
    s = SessionLocal()
    try:
        save_settings(s, {"cross_check_enabled": False, "cross_check_provider": "openai",
                          "labor_tariff_enabled": True, "labor_tariff_index": 1.0})
    finally:
        s.close()
