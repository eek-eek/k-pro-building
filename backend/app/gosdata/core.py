"""Валидация строк, upsert в БД и оркестрация импорта из CSV."""
from __future__ import annotations

import csv
import io
import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calc.units import unit_known
from ..models import GeneralizedIndicator
from .report import ImportReport


def _to_float(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _to_bool(value, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "да", "y"}


def _validate_generalized(row: dict) -> tuple[Optional[dict], Optional[str]]:
    object_type = (row.get("object_type") or "").strip()
    if not object_type:
        return None, "нет object_type"
    value = _to_float(row.get("value"))
    if value is None or value <= 0:
        return None, f"некорректное value: {row.get('value')!r}"
    unit = (row.get("unit") or "м²").strip()
    if not unit_known(unit):
        return None, f"неизвестная единица: {unit!r}"
    return {
        "object_type": object_type,
        "region": (row.get("region") or "KZ").strip(),
        "value": value,
        "unit": unit,
        "price_level": (row.get("price_level") or "import").strip(),
        "source_code": (row.get("source_code") or "").strip(),
        "source_url": (row.get("source_url") or "").strip(),
        "note": (row.get("note") or "").strip(),
        "needs_review": _to_bool(row.get("needs_review"), default=False),
    }, None


def _upsert_generalized(db: Session, c: dict) -> str:
    existing = db.scalar(
        select(GeneralizedIndicator).where(
            GeneralizedIndicator.object_type == c["object_type"],
            GeneralizedIndicator.region == c["region"],
            GeneralizedIndicator.price_level == c["price_level"],
        )
    )
    if existing is None:
        db.add(GeneralizedIndicator(**c))
        return "inserted"
    for k, v in c.items():
        setattr(existing, k, v)
    return "updated"


def run_import_generalized(db: Session, csv_text: str) -> ImportReport:
    report = ImportReport(target="generalized_indicators")
    reader = csv.DictReader(io.StringIO(csv_text))
    for i, row in enumerate(reader, start=2):  # 1 — заголовок
        clean, err = _validate_generalized(row)
        if err:
            report.skipped += 1
            report.errors.append(f"строка {i}: {err}")
            continue
        result = _upsert_generalized(db, clean)
        setattr(report, result, getattr(report, result) + 1)
    db.commit()
    return report
