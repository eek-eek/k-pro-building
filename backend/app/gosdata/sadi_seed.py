"""Сидирование справочников SADI.kz в БД: материалы (полный каталог с ценами)
и региональные тарифные ставки труда. Данные — компактные бандлы в ./sadi/.

Идемпотентно: если таблица уже заполнена, повторно не грузим (обход по флагу
пустоты — сброс dev-БД пересидирует). Вставка батчами через bulk-словарь."""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import LaborTariff, MaterialPrice

_DATA = Path(__file__).parent / "sadi"


def _load(name: str) -> dict:
    path = _DATA / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seed_materials(db: Session, batch: int = 2000) -> int:
    """Загрузить справочник материалов, если он ещё пуст. Возвращает число строк."""
    if db.scalar(select(func.count()).select_from(MaterialPrice)):
        return 0
    data = _load("materials.json")
    cats = data.get("cats", [])
    rows = data.get("rows", [])
    buf, added = [], 0
    for r in rows:
        code, name, unit, price, cat_idx = r
        buf.append({
            "code": code, "name": name, "name_lc": f"{code} {name}".lower(),
            "unit": unit or "", "price": price,
            "category": cats[cat_idx] if 0 <= cat_idx < len(cats) else "",
            "region": "KZ", "source": "sadi.kz",
        })
        if len(buf) >= batch:
            db.bulk_insert_mappings(MaterialPrice, buf)
            added += len(buf); buf = []
    if buf:
        db.bulk_insert_mappings(MaterialPrice, buf)
        added += len(buf)
    db.commit()
    return added


def seed_tariffs(db: Session) -> int:
    """Загрузить тарифные ставки труда, если таблица ещё пуста."""
    if db.scalar(select(func.count()).select_from(LaborTariff)):
        return 0
    data = _load("tariffs.json")
    edition = data.get("edition", "2016")
    buf = []
    for r in data.get("rows", []):
        region, kind, category, coef, rate, name = r
        buf.append({
            "region": region, "kind": kind, "category": category,
            "coef": coef, "rate": rate, "name": name,
            "edition": edition, "source": "sadi.kz",
        })
    if buf:
        db.bulk_insert_mappings(LaborTariff, buf)
    db.commit()
    return len(buf)


def seed_sadi(db: Session) -> tuple[int, int]:
    """Засеять оба справочника SADI. Возвращает (материалов, тарифов)."""
    return seed_materials(db), seed_tariffs(db)
