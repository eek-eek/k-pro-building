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
