"""Инициализация БД: таблицы, реестр норм, справочник цен."""
from __future__ import annotations

from .calc.pricing import seed_prices
from .database import SessionLocal, init_db
from .norms.registry import SEED_DOCUMENTS
from .norms.resolver import ensure_documents
from .prompts import seed_prompts

# Уникальные типы объектов из интерфейса.
OBJECT_TYPES = [
    "Жилой дом",
    "Коммерческое помещение",
    "Склад",
    "Офис",
    "Производственный объект",
    "Реконструкция / ремонт",
]


def run_seed() -> None:
    init_db()
    with SessionLocal() as db:
        for obj_type in OBJECT_TYPES:
            ensure_documents(db, obj_type)
        seed_prices(db)
        seed_prompts(db)


if __name__ == "__main__":
    run_seed()
    print(f"Seed готов: {len(SEED_DOCUMENTS)} документов, прайс засеян.")
