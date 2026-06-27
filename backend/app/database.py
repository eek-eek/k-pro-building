"""SQLAlchemy engine, session и базовый класс моделей."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _connection_record):
    """SQLite ignores FK constraints unless enabled per connection."""
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Создать таблицы (модели импортируются ради регистрации в метаданных)."""
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_estimate_object_id()


def _ensure_estimate_object_id() -> None:
    """Идемпотентно добавить estimates.object_id на старой БД (SQLite create_all
    не добавляет колонки в существующие таблицы)."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(estimates)")]
        if cols and "object_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE estimates ADD COLUMN object_id INTEGER")
