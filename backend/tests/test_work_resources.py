"""Каталог ресурсов в БД: идемпотентный сид из COMPOSITIONS с провенансом."""
from __future__ import annotations

from app.calc.resource_catalog import COMPOSITIONS, SEED_PRICE_LEVEL, seed_work_resources
from app.models import WorkResource


def test_work_resources_seeded_from_compositions(db):
    total_specs = sum(len(v) for v in COMPOSITIONS.values())
    rows = db.query(WorkResource).filter_by(region="KZ", price_level=SEED_PRICE_LEVEL).count()
    assert rows == total_specs


def test_seed_work_resources_idempotent(db):
    total_specs = sum(len(v) for v in COMPOSITIONS.values())
    seed_work_resources(db)  # повтор поверх уже засеянного из run_seed
    rows = db.query(WorkResource).filter_by(region="KZ", price_level=SEED_PRICE_LEVEL).count()
    assert rows == total_specs  # без дублей


def test_seed_provenance_and_units_clean(db):
    # Все сид-единицы каноничны → ни одна строка не помечена needs_review.
    flagged = db.query(WorkResource).filter_by(needs_review=True).count()
    assert flagged == 0
    sample = db.query(WorkResource).filter_by(work_key="frame_concrete", code="concrete_b25").first()
    assert sample is not None
    assert sample.source == "seed"
    assert sample.kind == "material"
    assert sample.consumption == 1.02
