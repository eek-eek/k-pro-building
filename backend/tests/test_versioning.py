import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models  # registers all tables


def _mem_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def test_estimate_version_chain_persists():
    db = _mem_session()
    est = models.Estimate(name="T", object_type="Жилой дом", city="Алматы")
    db.add(est)
    db.flush()
    v = models.EstimateVersion(
        estimate_id=est.id, version_number=1, input={}, result={},
        total=100.0, source="initial", summary="",
    )
    db.add(v)
    db.flush()
    est.current_version_id = v.id
    msg = models.ChatMessage(estimate_id=est.id, role="user", content="hi")
    db.add(msg)
    db.commit()
    assert est.current_version_id == v.id
    assert est.versions[0].version_number == 1
    assert est.chat_messages[0].content == "hi"


from app.versioning import create_version, next_version_number, summarize_diff
from app.schemas import BuildingInput, EstimateResult, EstimateTotals, EstimateLine


def _line(no, total):
    return EstimateLine(no=no, section="S", title="t", unit="м³", quantity=1,
                        material_price=total, total=total)


def _res(lines):
    return EstimateResult(project_name="p", city="c", object_type="o", lines=lines,
                          totals=EstimateTotals(grand_total=sum(l.total for l in lines)))


def test_next_version_number_increments_per_estimate():
    db = _mem_session()
    est = models.Estimate(name="T")
    db.add(est); db.flush()
    assert next_version_number(db, est.id) == 1
    db.add(models.EstimateVersion(estimate_id=est.id, version_number=1, input={},
                                  result={}, total=0, source="initial"))
    db.flush()
    assert next_version_number(db, est.id) == 2


def test_create_version_sets_pointer_and_fields():
    db = _mem_session()
    est = models.Estimate(name="T")
    db.add(est); db.flush()
    res = _res([_line("2.1", 100)])
    v = create_version(db, est, BuildingInput(), res, source="initial", summary="x")
    db.commit()
    assert v.version_number == 1
    assert est.current_version_id == v.id
    assert v.total == 100


def test_summarize_diff_reports_line_and_total_delta():
    prev = _res([_line("2.1", 100), _line("3.1", 200)])
    new = _res([_line("2.1", 100)])
    s = summarize_diff(prev, new)
    assert "−1 строк" in s
    assert "200" in s
    assert "₸" in s
