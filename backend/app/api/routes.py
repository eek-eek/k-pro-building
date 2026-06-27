"""REST + SSE эндпоинты."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..calc import build_estimate
from ..config import get_settings
from ..database import get_db
from ..jobs import job_manager
from ..models import Estimate, NormDocument, PriceItem
from ..norms import resolve_norm_profile
from ..schemas import BuildingInput, EstimateResult, JobStatus, to_jsonable

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "llm_provider": s.llm_provider}


@router.post("/estimate")
async def create_estimate(inp: BuildingInput) -> dict:
    """Создать задачу расчёта; вернуть job_id (расчёт идёт в фоне)."""
    runtime = job_manager.create()
    await job_manager.start(runtime, inp)
    return {"job_id": runtime.id}


@router.post("/estimate/sync", response_model=EstimateResult)
def create_estimate_sync(
    inp: BuildingInput, db: Session = Depends(get_db)
) -> EstimateResult:
    """Синхронный расчёт (без статусов) — для интеграций и тестов."""
    profile = resolve_norm_profile(db, inp)
    result = build_estimate(db, inp, profile)
    est = Estimate(
        input=to_jsonable(inp),
        result=to_jsonable(result),
        total=result.totals.grand_total,
    )
    db.add(est)
    db.commit()
    return result


@router.get("/estimate/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    runtime = job_manager.get(job_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="job not found")
    return runtime.snapshot()


@router.get("/estimate/{job_id}/events")
async def stream_events(job_id: str):
    runtime = job_manager.get(job_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_gen():
        async for status in job_manager.events(job_id):
            yield {
                "event": "status",
                "data": json.dumps(to_jsonable(status), ensure_ascii=False),
            }
        yield {"event": "end", "data": "{}"}

    return EventSourceResponse(event_gen())


@router.get("/estimates/{estimate_id}")
def get_estimate(estimate_id: int, db: Session = Depends(get_db)) -> dict:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    return {"id": est.id, "total": est.total, "result": est.result}


@router.get("/norms")
def list_norms(db: Session = Depends(get_db)) -> list[dict]:
    docs = db.scalars(select(NormDocument).order_by(NormDocument.code)).all()
    return [
        {
            "code": d.code,
            "title": d.title,
            "doc_type": d.doc_type,
            "url": d.url,
            "object_types": d.object_types,
            "status": d.status,
        }
        for d in docs
    ]


@router.get("/prices")
def list_prices(db: Session = Depends(get_db)) -> list[dict]:
    items = db.scalars(select(PriceItem).order_by(PriceItem.key)).all()
    return [
        {
            "key": i.key,
            "title": i.title,
            "unit": i.unit,
            "material": i.material_price,
            "labor": i.labor_price,
            "machine": i.machine_price,
            "region": i.region,
        }
        for i in items
    ]
