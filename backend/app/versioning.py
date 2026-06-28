"""Helpers to snapshot estimate versions and describe their diffs."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Estimate, EstimateVersion
from .schemas import BuildingInput, EstimateResult, to_jsonable


def next_version_number(db: Session, estimate_id: int) -> int:
    current = db.scalar(
        select(func.max(EstimateVersion.version_number)).where(
            EstimateVersion.estimate_id == estimate_id
        )
    )
    return (current or 0) + 1


def _money(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}{abs(round(value)):,}".replace(",", " ") + " ₸"


def summarize_diff(prev: EstimateResult, new: EstimateResult) -> str:
    added = len(new.lines) - len(prev.lines)
    parts = []
    if added > 0:
        parts.append(f"+{added} строк")
    elif added < 0:
        parts.append(f"−{abs(added)} строк")
    delta = new.totals.grand_total - prev.totals.grand_total
    if round(delta) != 0:
        parts.append(_money(delta))
    return ", ".join(parts) or "без изменений итогов"


def create_version(
    db: Session,
    estimate: Estimate,
    inp: BuildingInput,
    result: EstimateResult,
    *,
    source: str,
    summary: str = "",
) -> EstimateVersion:
    """Create a new immutable version, advance the pointer, refresh denorm fields.
    Retries once on a version_number collision."""
    for attempt in range(2):
        version = EstimateVersion(
            estimate_id=estimate.id,
            version_number=next_version_number(db, estimate.id),
            input=to_jsonable(inp),
            result=to_jsonable(result),
            total=result.totals.grand_total,
            source=source,
            summary=summary,
        )
        sp = db.begin_nested()
        db.add(version)
        try:
            db.flush()
            sp.commit()
            break
        except IntegrityError:
            sp.rollback()
            if attempt == 1:
                raise
    estimate.current_version_id = version.id
    estimate.status = "calculated"
    estimate.object_type = inp.object_type
    estimate.city = inp.city
    if not estimate.name:
        estimate.name = inp.project_name or f"Смета #{estimate.id}"
    db.flush()
    return version
