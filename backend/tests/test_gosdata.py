"""Импорт официального ресурсного каталога цен РК из CSV (app.gosdata)."""
from __future__ import annotations

from app.gosdata.core import run_import_resources
from app.models import WorkResource


def test_import_resources_inserts_and_validates(db):
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


def test_cli_resources(tmp_path):
    # Синтетические ключи — не задевают сидовый каталог.
    from app.gosdata.__main__ import main
    p = tmp_path / "r.csv"
    p.write_text("work_key,code,name,kind,unit,consumption,price,region,price_level,source\n"
                 "frame_concrete,cli_mat,Тест,material,м³,1,1000,ТестРегион,ТестУровень,manual\n",
                 encoding="utf-8")
    rc = main(["app.gosdata", "resources", str(p)])
    assert rc == 0


def test_cli_bad_args():
    from app.gosdata.__main__ import main
    assert main(["app.gosdata"]) == 2
    assert main(["app.gosdata", "wat", "x.csv"]) == 2
