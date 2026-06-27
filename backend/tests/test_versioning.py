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
