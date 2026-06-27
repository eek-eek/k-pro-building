from sqlalchemy import text
from app.database import engine


def test_foreign_keys_pragma_on():
    with engine.connect() as conn:
        val = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert val == 1
