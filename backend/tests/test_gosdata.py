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


def test_import_resources_inserts_and_validates(db):
    from app.gosdata.core import run_import_resources
    from app.models import WorkResource
    csv_text = """work_key,code,name,kind,unit,consumption,price,region,price_level,source,needs_review
frame_concrete,concrete_b25,Бетон B25,material,м³,1.02,31000,Астана,ССЦ-2026,ssc,false
frame_concrete,concreter_x,Бетонщик,labor,чел-ч,2.9,3600,Астана,ССЦ-2026,erer,false
frame_concrete,bad_unit,Кривой,labor,м³,1,100,Астана,ССЦ-2026,erer,false
"""
    report = run_import_resources(db, csv_text)
    assert report.inserted == 2 and report.skipped == 1  # labor с единицей м³ отбракован
    assert any("kind" in e or "единиц" in e for e in report.errors)
    row = db.query(WorkResource).filter_by(
        work_key="frame_concrete", code="concrete_b25",
        region="Астана", price_level="ССЦ-2026").first()
    assert row is not None and row.price == 31000 and row.source == "ssc"


def test_cli_generalized(tmp_path):
    from app.gosdata.__main__ import main
    p = tmp_path / "g.csv"
    p.write_text("object_type,value,price_level\nСклад,175000,ССЦ-2026\n", encoding="utf-8")
    rc = main(["app.gosdata", "generalized", str(p)])
    assert rc == 0


def test_cli_bad_args():
    from app.gosdata.__main__ import main
    assert main(["app.gosdata"]) == 2
    assert main(["app.gosdata", "wat", "x.csv"]) == 2
