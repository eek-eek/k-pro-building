from app.database import SessionLocal
from app.seed import run_seed
from app.prompts import get_prompt, PROMPT_DEFAULTS


def test_seed_creates_default_prompts():
    run_seed()
    db = SessionLocal()
    try:
        body = get_prompt(db, "norm_extraction")
        assert "нормировщик" in body.lower()
        assert "estimate_edit" in PROMPT_DEFAULTS
    finally:
        db.close()


def test_get_prompt_falls_back_to_code_default_when_db_empty():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app import models  # noqa: F401  (registers tables)

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    try:
        # no seeding → no rows → code default returned
        assert get_prompt(db, "estimate_edit") == PROMPT_DEFAULTS["estimate_edit"]["body"]
        # unknown key → empty string
        assert get_prompt(db, "__nonexistent__") == ""
    finally:
        db.close()
