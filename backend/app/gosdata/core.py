"""Валидация строк, upsert в БД и оркестрация импорта из CSV."""
from __future__ import annotations

import csv
import io
import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calc.units import unit_ok_for_kind
from ..models import WorkResource
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


_KINDS = {"material", "labor", "machine"}


def _validate_work_resource(row: dict) -> tuple[Optional[dict], Optional[str]]:
    work_key = (row.get("work_key") or "").strip()
    code = (row.get("code") or "").strip()
    if not work_key or not code:
        return None, "нет work_key/code"
    kind = (row.get("kind") or "").strip()
    if kind not in _KINDS:
        return None, f"некорректный kind: {kind!r}"
    unit = (row.get("unit") or "").strip()
    if not unit_ok_for_kind(unit, kind):
        return None, f"единица {unit!r} не подходит для вида {kind}"
    consumption = _to_float(row.get("consumption"))
    price = _to_float(row.get("price"))
    if consumption is None or consumption < 0:
        return None, f"некорректное consumption: {row.get('consumption')!r}"
    if price is None or price < 0:
        return None, f"некорректное price: {row.get('price')!r}"
    return {
        "work_key": work_key,
        "code": code,
        "official_code": (row.get("official_code") or "").strip(),
        "name": (row.get("name") or code).strip(),
        "kind": kind,
        "unit": unit,
        "consumption": consumption,
        "rank": (row.get("rank") or "").strip(),
        "price": price,
        "source": (row.get("source") or "import").strip(),
        "price_level": (row.get("price_level") or "import").strip(),
        "region": (row.get("region") or "KZ").strip(),
        "needs_review": _to_bool(row.get("needs_review"), default=False),
    }, None


def _upsert_work_resource(db: Session, c: dict) -> str:
    existing = db.scalar(
        select(WorkResource).where(
            WorkResource.work_key == c["work_key"],
            WorkResource.code == c["code"],
            WorkResource.region == c["region"],
            WorkResource.price_level == c["price_level"],
        )
    )
    if existing is None:
        db.add(WorkResource(**c))
        return "inserted"
    for k, v in c.items():
        setattr(existing, k, v)
    return "updated"


def import_resource_rows(db: Session, rows, *,
                         force_price_level: str | None = None,
                         force_source: str | None = None) -> ImportReport:
    """Импорт ресурсов из итерируемого набора dict-строк (CSV или xlsx).
    force_price_level/force_source перекрывают значения из файла (напр. для загрузки
    внутреннего бенчмаркинга — price_level=бенчмарк)."""
    report = ImportReport(target="work_resources")
    for i, row in enumerate(rows, start=2):
        clean, err = _validate_work_resource(row)
        if err:
            report.skipped += 1
            report.errors.append(f"строка {i}: {err}")
            continue
        if force_price_level:
            clean["price_level"] = force_price_level
        if force_source:
            clean["source"] = force_source
        result = _upsert_work_resource(db, clean)
        setattr(report, result, getattr(report, result) + 1)
    db.commit()
    return report


def run_import_resources(db: Session, csv_text: str, *,
                         force_price_level: str | None = None,
                         force_source: str | None = None) -> ImportReport:
    """Импорт ресурсов из CSV-текста."""
    return import_resource_rows(db, csv.DictReader(io.StringIO(csv_text)),
                                force_price_level=force_price_level, force_source=force_source)
