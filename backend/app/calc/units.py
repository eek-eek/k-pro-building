"""Реестр канонических единиц измерения ресурсного метода + валидация kind↔единица.

Единый источник правды по единицам. Строки совпадают с используемыми в
COMPOSITIONS, чтобы сид каталога не требовал переименования значений.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Unit

# Каноническая единица → размерность.
UNIT_DIMENSION: dict[str, str] = {
    "чел-ч": "labor_time",
    "маш-ч": "machine_time",
    "маш-см": "machine_time",
    "м³": "volume",
    "л": "volume",
    "м²": "area",
    "м": "length",
    "км": "length",
    "т": "mass",
    "кг": "mass",
    "шт": "count",
    "компл": "set",
}

# Допустимые размерности для вида ресурса.
KIND_DIMENSIONS: dict[str, set[str]] = {
    "labor": {"labor_time"},
    "machine": {"machine_time"},
    "material": {"mass", "volume", "area", "count", "length", "set"},
}

# Человекочитаемые ярлыки (для реестра/UI).
UNIT_TITLE: dict[str, str] = {
    "чел-ч": "человеко-час", "маш-ч": "машино-час", "маш-см": "машино-смена",
    "м³": "кубический метр", "м²": "квадратный метр", "м": "метр", "км": "километр",
    "т": "тонна", "кг": "килограмм", "шт": "штука", "компл": "комплект", "л": "литр",
}


def unit_known(unit: str) -> bool:
    return unit in UNIT_DIMENSION


def unit_ok_for_kind(unit: str, kind: str) -> bool:
    """True, если единица существует и её размерность допустима для вида ресурса."""
    dim = UNIT_DIMENSION.get(unit)
    if dim is None:
        return False
    return dim in KIND_DIMENSIONS.get(kind, set())


def seed_units(db: Session) -> None:
    """Идемпотентно засеять реестр единиц в БД."""
    for code, dim in UNIT_DIMENSION.items():
        if db.get(Unit, code) is None:
            db.add(Unit(code=code, title=UNIT_TITLE.get(code, code), dimension=dim))
    db.commit()
