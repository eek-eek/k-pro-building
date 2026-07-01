"""Инициализация БД: таблицы, реестр норм, справочник цен."""
from __future__ import annotations

from .calc.pricing import seed_prices
from .calc.resource_catalog import seed_work_resources
from .calc.units import seed_units
from .database import SessionLocal, init_db
from .gosdata.sadi_seed import seed_sadi
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
        seed_units(db)
        seed_work_resources(db)
        seed_prompts(db)
        seed_sadi(db)  # справочники SADI: материалы (27k) + тарифы труда (16 регионов)


if __name__ == "__main__":
    run_seed()
    print(f"Seed готов: {len(SEED_DOCUMENTS)} документов, прайс засеян.")
