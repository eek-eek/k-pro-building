from app.database import SessionLocal, engine
from app.seed import run_seed
from app.models import BuildingObject, Estimate


def test_building_object_table_and_estimate_fk():
    run_seed()
    # колонка object_id есть в estimates
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(estimates)")]
    assert "object_id" in cols
    # объект создаётся и привязывается к смете
    db = SessionLocal()
    try:
        obj = BuildingObject(name="Тест", city="Алматы", lat=43.24, lon=76.9, area_m2=1000.0)
        db.add(obj); db.commit()
        est = Estimate(name="С", object_type="Жилой дом", city="Алматы", object_id=obj.id)
        db.add(est); db.commit()
        assert est.object_id == obj.id
    finally:
        db.close()
