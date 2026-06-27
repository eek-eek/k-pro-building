"""REST + SSE эндпоинты."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..calc import build_estimate
from ..config import get_settings
from ..database import get_db
from ..jobs import job_manager
from ..models import Estimate, EstimateVersion, ChatMessage, NormDocument, PriceItem
from ..norms import resolve_norm_profile
from ..schemas import (
    BuildingInput, EstimateCard, EstimateCreate, EstimatePatch,
    EstimateResult, JobStatus, to_jsonable,
)
from ..versioning import create_version

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "llm_provider": s.llm_provider}


@router.post("/estimate")
async def create_estimate(inp: BuildingInput, db: Session = Depends(get_db)) -> dict:
    """Создать задачу расчёта; вернуть job_id (расчёт идёт в фоне)."""
    est = Estimate(name=inp.project_name, object_type=inp.object_type, city=inp.city)
    db.add(est)
    db.commit()
    runtime = job_manager.create(est.id)
    await job_manager.start(runtime, inp)
    return {"job_id": runtime.id, "estimate_id": est.id}


@router.post("/estimate/sync")
def create_estimate_sync(inp: BuildingInput, db: Session = Depends(get_db)) -> dict:
    """Synchronous calc — creates an Estimate container + initial version."""
    profile = resolve_norm_profile(db, inp)
    result = build_estimate(db, inp, profile)
    estimate = Estimate(name=inp.project_name, object_type=inp.object_type, city=inp.city)
    db.add(estimate)
    db.flush()
    version = create_version(db, estimate, inp, result, source="initial")
    db.commit()
    return {
        "estimate_id": estimate.id,
        "version_number": version.version_number,
        "result": to_jsonable(result),
    }


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


def _card(db: Session, est: Estimate) -> EstimateCard:
    total = est.current_version.total if est.current_version else 0.0
    vcount = db.query(EstimateVersion).filter_by(estimate_id=est.id).count()
    mcount = db.query(ChatMessage).filter_by(estimate_id=est.id).count()
    return EstimateCard(
        id=est.id, name=est.name, object_type=est.object_type, city=est.city,
        status=est.status, total=total, version_count=vcount, message_count=mcount,
        updated_at=est.updated_at.isoformat(timespec="seconds"),
    )


@router.get("/estimates")
def list_estimates(db: Session = Depends(get_db)) -> list[EstimateCard]:
    rows = db.scalars(select(Estimate).order_by(Estimate.updated_at.desc())).all()
    return [_card(db, e) for e in rows]


@router.post("/estimates")
def create_estimate_container(body: EstimateCreate, db: Session = Depends(get_db)) -> dict:
    inp = body.input or BuildingInput()
    est = Estimate(name=body.name or inp.project_name,
                   object_type=inp.object_type, city=inp.city, status="draft")
    db.add(est)
    db.commit()
    return {"id": est.id}


@router.get("/estimates/{estimate_id}")
def get_estimate_full(estimate_id: int, db: Session = Depends(get_db)) -> dict:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    cv = est.current_version
    return {
        "estimate": {"id": est.id, "name": est.name, "object_type": est.object_type,
                     "city": est.city, "status": est.status},
        "current_version": ({"version_number": cv.version_number, "input": cv.input,
                             "result": cv.result, "source": cv.source} if cv else None),
        "version_count": db.query(EstimateVersion).filter_by(estimate_id=est.id).count(),
        "message_count": db.query(ChatMessage).filter_by(estimate_id=est.id).count(),
    }


@router.patch("/estimates/{estimate_id}")
def patch_estimate(estimate_id: int, body: EstimatePatch,
                   db: Session = Depends(get_db)) -> dict:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    if body.name is not None:
        est.name = body.name
    if body.input is not None:
        est.object_type = body.input.object_type
        est.city = body.input.city
    db.commit()
    return {"ok": True}


@router.delete("/estimates/{estimate_id}", status_code=204)
def delete_estimate(estimate_id: int, db: Session = Depends(get_db)) -> Response:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    est.current_version_id = None
    db.flush()
    db.delete(est)
    db.commit()
    return Response(status_code=204)


@router.post("/estimates/{estimate_id}/calc")
async def calc_estimate(estimate_id: int, db: Session = Depends(get_db)) -> dict:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    cv = est.current_version
    if cv is not None:
        inp = BuildingInput(**cv.input)
    else:
        inp = BuildingInput(project_name=est.name or "Смета",
                            object_type=est.object_type or "Жилой дом",
                            city=est.city or "Астана / Казахстан")
    runtime = job_manager.create(estimate_id)
    await job_manager.start(runtime, inp)
    return {"job_id": runtime.id}


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
