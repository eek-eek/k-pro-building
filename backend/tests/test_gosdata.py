"""Импорт официальных данных РК из CSV (app/gosdata)."""
from __future__ import annotations

from app.gosdata.core import run_import_generalized
from app.models import GeneralizedIndicator

_CSV = """object_type,region,value,unit,price_level,source_code,needs_review
Жилой дом,Астана,310000,м²,ССЦ-2026,НДЦС РК 8.02-01-2025,false
Офис,Астана,355000,м²,ССЦ-2026,НДЦС РК 8.02-01-2025,false
"""


def test_import_generalized_inserts(db):
    report = run_import_generalized(db, _CSV)
    assert report.inserted == 2 and report.skipped == 0 and not report.errors
    row = db.query(GeneralizedIndicator).filter_by(
        object_type="Жилой дом", region="Астана", price_level="ССЦ-2026").first()
    assert row is not None
    assert row.value == 310000
    assert row.source_code == "НДЦС РК 8.02-01-2025"
    assert row.needs_review is False  # официальные данные из файла


def test_import_generalized_idempotent_upsert(db):
    run_import_generalized(db, _CSV)
    r2 = run_import_generalized(db, _CSV.replace("310000", "315000"))
    assert r2.updated == 2 and r2.inserted == 0  # те же ключи → обновление
    row = db.query(GeneralizedIndicator).filter_by(
        object_type="Жилой дом", region="Астана", price_level="ССЦ-2026").first()
    assert row.value == 315000


def test_import_generalized_quarantines_bad_rows(db):
    bad = """object_type,region,value,unit,price_level
,Астана,1,м²,X
Жилой дом,Астана,-5,м²,X
Жилой дом,Астана,100,попугай,X
"""
    report = run_import_generalized(db, bad)
    assert report.inserted == 0 and report.skipped == 3
    assert len(report.errors) == 3  # нет object_type / value<0 / неизвестная единица
