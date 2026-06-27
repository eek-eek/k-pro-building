"""REST + SSE эндпоинты."""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..calc import (
    build_estimate, recompute_estimate,
    applicable_recommendations, build_recommendation_line,
)
from ..chat import run_chat_edit, ChatUnavailable, ChatEditError
from ..database import get_db
from ..jobs import job_manager
from ..models import Estimate, EstimateVersion, ChatMessage, NormDocument, PriceItem, Prompt
from ..norms import resolve_norm_profile
from ..pricesource import get_price_source, available_sources
from ..prompts import PROMPT_DEFAULTS
from ..schemas import (
    BuildingInput, ChatPost, EstimateCard, EstimateCreate, EstimatePatch,
    EstimateResult, JobStatus, ManualEditRequest, NormSource, RecommendationAdd, RollbackRequest,
    to_jsonable, SettingsUpdate, TestConnectionRequest, PromptUpdate, SuggestPricesRequest,
)
from ..settings_service import get_effective_settings, save_settings, mask_key, MODEL_CATALOG, test_provider as run_test_provider
from ..versioning import create_version, summarize_diff

router = APIRouter(prefix="/api")


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    eff = get_effective_settings(db)
    return {"status": "ok", "llm_provider": eff.llm_provider}


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
async def calc_estimate(estimate_id: int, body: BuildingInput | None = Body(None),
                        db: Session = Depends(get_db)) -> dict:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    if body is not None:
        inp = body
    elif est.current_version is not None:
        inp = BuildingInput(**est.current_version.input)
    else:
        inp = BuildingInput(project_name=est.name or "Смета",
                            object_type=est.object_type or "Жилой дом",
                            city=est.city or "Астана / Казахстан")
    # keep dashboard denorm fields in sync with the input being calculated
    est.object_type = inp.object_type
    est.city = inp.city
    if not est.name:
        est.name = inp.project_name
    db.commit()
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


@router.get("/estimates/{estimate_id}/versions")
def list_versions(estimate_id: int, db: Session = Depends(get_db)) -> list[dict]:
    if db.get(Estimate, estimate_id) is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    rows = db.scalars(
        select(EstimateVersion).where(EstimateVersion.estimate_id == estimate_id)
        .order_by(EstimateVersion.version_number)
    ).all()
    return [{"version_number": v.version_number, "source": v.source,
             "summary": v.summary, "total": v.total,
             "created_at": v.created_at.isoformat(timespec="seconds")} for v in rows]


@router.get("/estimates/{estimate_id}/versions/{version_number}")
def get_version(estimate_id: int, version_number: int,
                db: Session = Depends(get_db)) -> dict:
    v = db.scalar(select(EstimateVersion).where(
        EstimateVersion.estimate_id == estimate_id,
        EstimateVersion.version_number == version_number))
    if v is None:
        raise HTTPException(status_code=404, detail="version not found")
    return {"version_number": v.version_number, "source": v.source,
            "input": v.input, "result": v.result, "summary": v.summary}


@router.post("/estimates/{estimate_id}/manual-edit")
def manual_edit(estimate_id: int, body: ManualEditRequest,
                db: Session = Depends(get_db)) -> dict:
    est = db.get(Estimate, estimate_id)
    if est is None or est.current_version is None:
        raise HTTPException(status_code=404, detail="estimate not calculated")
    prev = EstimateResult(**est.current_version.result)
    inp = body.input or BuildingInput(**est.current_version.input)
    new_result = recompute_estimate(prev, body.lines, inp)
    new_json = to_jsonable(new_result)
    cur = est.current_version.result
    # Ничего не изменилось — не плодим версию (recompute детерминирован/идемпотентен).
    if (new_json["lines"] == cur.get("lines")
            and new_json["totals"] == cur.get("totals")
            and new_json["section_totals"] == cur.get("section_totals")):
        return {"version_number": est.current_version.version_number,
                "result": cur, "unchanged": True}
    summary = summarize_diff(prev, new_result)
    version = create_version(db, est, inp, new_result, source="manual_edit", summary=summary)
    db.commit()
    return {"version_number": version.version_number, "result": new_json}


def _check_link(url: str):
    """Доступность ссылки: True (2xx/3xx) / False (HTTP 4xx/5xx — битая/устаревшая) /
    None (таймаут/блокировка — не удалось проверить). GET с браузерным UA и следованием
    редиректам (HEAD многие гос-сайты не отдают). Проверка SSL-сертификата отключена
    намеренно: это проба доступности публичной ссылки, а не передача данных — Python на
    macOS часто не находит системные CA, из-за чего живые сайты (напр. adilet.zan.kz)
    ложно падали в ошибку."""
    import ssl
    import urllib.error
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=6, context=ctx) as r:
            return 200 <= r.status < 400
    except urllib.error.HTTPError as e:
        return False if 400 <= e.code < 600 else None
    except Exception:
        return None


@router.post("/estimates/{estimate_id}/verify-norms")
def verify_norms(estimate_id: int, db: Session = Depends(get_db)) -> dict:
    """Проверка норм: (1) доступность ссылок источников (всегда), (2) подтверждение/
    дополнение через LLM (если провайдер с ключом). Источники обновляются в текущей
    версии на месте — без создания новой версии."""
    est = db.get(Estimate, estimate_id)
    if est is None or est.current_version is None:
        raise HTTPException(status_code=404, detail="estimate not calculated")
    cv = est.current_version
    try:
        inp = BuildingInput(**cv.input)
        inp.use_search = True
        inp.demo_mode = False  # пытаемся подтвердить через LLM; без ключа — тихо деградирует
        sources = resolve_norm_profile(db, inp).sources
    except Exception:
        sources = [NormSource(**s) for s in cv.result.get("sources", [])]
    for s in sources:
        s.link_ok = _check_link(s.url) if s.url else None
    cv.result = {**cv.result, "sources": [to_jsonable(s) for s in sources]}
    db.commit()
    return {
        "sources": [to_jsonable(s) for s in sources],
        "checked": len(sources),
        "confirmed": sum(1 for s in sources if s.confirmed),
        "links_ok": sum(1 for s in sources if s.link_ok is True),
        "llm": any(s.confirmed for s in sources),
    }


@router.get("/estimates/{estimate_id}/recommendations")
def list_recommendations(estimate_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """Ещё не учтённые типовые позиции по нормам РК с уже рассчитанной стоимостью."""
    est = db.get(Estimate, estimate_id)
    if est is None or est.current_version is None:
        return []
    result = EstimateResult(**est.current_version.result)
    inp = BuildingInput(**est.current_version.input)
    return applicable_recommendations(inp, result)


@router.post("/estimates/{estimate_id}/recommendations")
def add_recommendation(estimate_id: int, body: RecommendationAdd,
                       db: Session = Depends(get_db)) -> dict:
    """Добавить рекомендацию в смету: сервер сам считает объём и цены по укрупнённым
    показателям, дописывает строку и пересчитывает итоги (новая версия)."""
    est = db.get(Estimate, estimate_id)
    if est is None or est.current_version is None:
        raise HTTPException(status_code=404, detail="estimate not calculated")
    prev = EstimateResult(**est.current_version.result)
    inp = BuildingInput(**est.current_version.input)
    try:
        new_line = build_recommendation_line(body.key, inp, prev)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown recommendation")
    new_result = recompute_estimate(prev, list(prev.lines) + [new_line], inp)
    summary = f"рекомендация: {new_line.title} ({summarize_diff(prev, new_result)})"
    version = create_version(db, est, inp, new_result, source="manual_edit", summary=summary)
    db.commit()
    return {"version_number": version.version_number, "result": to_jsonable(new_result)}


@router.get("/price-sources")
def list_price_sources() -> list[dict]:
    return available_sources()


@router.post("/estimates/{estimate_id}/suggest-material-prices")
def suggest_material_prices(estimate_id: int, body: SuggestPricesRequest,
                            db: Session = Depends(get_db)) -> dict:
    est = db.get(Estimate, estimate_id)
    if est is None or est.current_version is None:
        raise HTTPException(status_code=404, detail="estimate not calculated")
    result = EstimateResult(**est.current_version.result)
    codes: list[str] = []
    seen: set[str] = set()
    for ln in result.lines:
        for r in (ln.resources or []):
            if r.kind == "material" and r.code not in seen:
                seen.add(r.code)
                codes.append(r.code)
    quotes = get_price_source(body.source).quote_materials(codes)
    return {
        "source": body.source,
        "suggestions": {c: {"price": q.price, "source": q.source, "note": q.note}
                        for c, q in quotes.items()},
    }


@router.post("/estimates/{estimate_id}/rollback")
def rollback(estimate_id: int, body: RollbackRequest,
             db: Session = Depends(get_db)) -> dict:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    target = db.scalar(select(EstimateVersion).where(
        EstimateVersion.estimate_id == estimate_id,
        EstimateVersion.version_number == body.version_number))
    if target is None:
        raise HTTPException(status_code=404, detail="version not found")
    inp = BuildingInput(**target.input)
    result = EstimateResult(**target.result)
    version = create_version(db, est, inp, result, source="rollback",
                             summary=f"откат к версии {body.version_number}")
    db.commit()
    return {"version_number": version.version_number, "result": target.result}


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


@router.get("/estimates/{estimate_id}/chat")
def list_chat(estimate_id: int, db: Session = Depends(get_db)) -> list[dict]:
    if db.get(Estimate, estimate_id) is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.estimate_id == estimate_id)
        .order_by(ChatMessage.id)
    ).all()
    vmap = {v.id: v.version_number for v in db.scalars(
        select(EstimateVersion).where(EstimateVersion.estimate_id == estimate_id)).all()}
    return [{"role": m.role, "content": m.content,
             "version_number": vmap.get(m.version_id) if m.version_id is not None else None,
             "created_at": m.created_at.isoformat(timespec="seconds")} for m in rows]


@router.post("/estimates/{estimate_id}/chat")
def post_chat(estimate_id: int, body: ChatPost, db: Session = Depends(get_db)) -> dict:
    """Sync handler → runs in FastAPI threadpool, so the blocking LLM call does
    not block the event loop and the request session stays on one thread."""
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    try:
        return run_chat_edit(db, est, body.message)
    except ChatUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db)) -> dict:
    eff = get_effective_settings(db)
    return {
        "provider": eff.llm_provider,
        "model": eff.active_model(),
        "masked_key": mask_key(eff.active_key()),
        "has_key": bool(eff.active_key()),
        "use_search": eff.llm_use_search,
        "catalog": MODEL_CATALOG,
    }


@router.put("/settings")
def put_settings_api(body: SettingsUpdate, db: Session = Depends(get_db)) -> dict:
    eff = get_effective_settings(db)
    provider = (body.provider or eff.llm_provider).lower()
    updates: dict = {}
    if body.provider is not None:
        updates["llm_provider"] = provider
    if body.model is not None:
        updates[f"{provider}_model"] = body.model
    if body.use_search is not None:
        updates["llm_use_search"] = body.use_search
    if body.api_key is not None and body.api_key != "":
        if body.api_key != mask_key(getattr(eff, f"{provider}_api_key", "")):
            updates[f"{provider}_api_key"] = body.api_key
    save_settings(db, updates)
    return get_settings_api(db)


@router.post("/settings/test")
def test_connection_api(body: TestConnectionRequest, db: Session = Depends(get_db)) -> dict:
    ok, message = run_test_provider(db, body.provider, body.api_key, body.model)
    return {"ok": ok, "message": message}


@router.get("/prompts")
def list_prompts(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Prompt).order_by(Prompt.key)).all()
    return [{"key": p.key, "title": p.title, "description": p.description,
             "body": p.body, "is_custom": p.is_custom} for p in rows]


@router.put("/prompts/{key}")
def update_prompt(key: str, body: PromptUpdate, db: Session = Depends(get_db)) -> dict:
    row = db.scalar(select(Prompt).where(Prompt.key == key))
    if row is None:
        raise HTTPException(status_code=404, detail="prompt not found")
    row.body = body.body
    row.is_custom = True
    db.commit()
    return {"ok": True}


@router.post("/prompts/{key}/reset")
def reset_prompt(key: str, db: Session = Depends(get_db)) -> dict:
    row = db.scalar(select(Prompt).where(Prompt.key == key))
    if row is None:
        raise HTTPException(status_code=404, detail="prompt not found")
    default = PROMPT_DEFAULTS.get(key)
    if default is None:
        raise HTTPException(status_code=404, detail="no default for prompt")
    row.body = default["body"]
    row.is_custom = False
    db.commit()
    return {"ok": True}
