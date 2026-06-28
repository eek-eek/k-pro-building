"""Резолв нормативного профиля под объект: cache → DB rules → LLM → defaults."""
from __future__ import annotations

import datetime as dt
import json
import threading
from collections.abc import Callable
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..llm.base import LLMUnavailable
from ..models import KnowledgeCache, NormDocument, NormRule
from ..schemas import BuildingInput, NormParam, NormProfile, NormSource
from . import extractor
from .defaults import resolve_defaults
from .registry import documents_for

ProgressFn = Callable[[str, str], None]

_SOURCE_RANK = {"document": 4, "seed": 3, "llm": 2, "default": 1}

# Сериализация per-signature: одновременные одинаковые запросы не должны
# дублировать обращения к LLM и гонять вставку в кэш.
_sig_locks_guard = threading.Lock()
_sig_locks: dict[str, threading.Lock] = {}


def _lock_for(signature: str) -> threading.Lock:
    with _sig_locks_guard:
        lock = _sig_locks.get(signature)
        if lock is None:
            lock = threading.Lock()
            _sig_locks[signature] = lock
        return lock


def _cond_key(conditions: dict) -> str:
    """Стабильный ключ условий для дедупликации правил."""
    return json.dumps(conditions or {}, ensure_ascii=False, sort_keys=True)


def _noop(_key: str, _detail: str) -> None:  # pragma: no cover
    pass


def _input_attrs(inp: BuildingInput) -> dict[str, str]:
    # Тот же набор, что и в сигнатуре кэша — чтобы правило не «протекало»
    # на вход, отличающийся отделкой/инженерией/регионом и т.п.
    return inp.discriminators()


def _conditions_match(conditions: dict, attrs: dict[str, str]) -> bool:
    for key, expected in (conditions or {}).items():
        if attrs.get(key) != expected:
            return False
    return True


def _better(a: NormParam, b: NormParam) -> NormParam:
    """Выбрать более авторитетный параметр."""
    ra, rb = _SOURCE_RANK.get(a.source, 0), _SOURCE_RANK.get(b.source, 0)
    if ra != rb:
        return a if ra > rb else b
    return a if a.confidence >= b.confidence else b


def ensure_documents(db: Session, object_type: str) -> list[NormDocument]:
    """Засеять/синхронизировать (idempotent) и вернуть документы для типа объекта.
    Реестр — источник истины: реестровые поля (URL/заголовок/тип/типы объектов)
    обновляются на существующих записях, если изменились (напр. починили ссылку)."""
    result: list[NormDocument] = []
    for code, title, doc_type, url, obj_types in documents_for(object_type):
        doc = db.scalar(select(NormDocument).where(NormDocument.code == code))
        if doc is None:
            doc = NormDocument(
                code=code,
                title=title,
                doc_type=doc_type,
                url=url,
                object_types=obj_types,
                status="seed",
            )
            db.add(doc)
            db.flush()
        elif (doc.url, doc.title, doc.doc_type, doc.object_types) != (url, title, doc_type, obj_types):
            doc.url = url
            doc.title = title
            doc.doc_type = doc_type
            doc.object_types = obj_types
        result.append(doc)
    db.commit()
    return result


def _cache_get(db: Session, signature: str) -> Optional[NormProfile]:
    s = get_settings()
    row = db.scalar(select(KnowledgeCache).where(KnowledgeCache.signature == signature))
    if row is None:
        return None
    if s.knowledge_cache_ttl_days > 0:
        created = row.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        age = dt.datetime.now(dt.timezone.utc) - created
        if age.days > s.knowledge_cache_ttl_days:
            return None
    profile = NormProfile.model_validate(row.profile)
    profile.from_cache = True
    return profile


def _cache_put(db: Session, profile: NormProfile) -> None:
    existing = db.scalar(
        select(KnowledgeCache).where(KnowledgeCache.signature == profile.signature)
    )
    payload = profile.model_dump()
    payload["from_cache"] = False
    if existing:
        existing.profile = payload
        existing.created_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
        return
    db.add(
        KnowledgeCache(
            signature=profile.signature,
            object_type=profile.object_type,
            profile=payload,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Параллельный резолв уже вставил запись с этой сигнатурой — обновим её.
        db.rollback()
        row = db.scalar(
            select(KnowledgeCache).where(
                KnowledgeCache.signature == profile.signature
            )
        )
        if row is not None:
            row.profile = payload
            row.created_at = dt.datetime.now(dt.timezone.utc)
            db.commit()


def _rules_from_db(db: Session, inp: BuildingInput) -> dict[str, NormParam]:
    attrs = _input_attrs(inp)
    rows = db.scalars(
        select(NormRule).where(NormRule.object_type == inp.object_type)
    ).all()
    out: dict[str, NormParam] = {}
    for r in rows:
        if not _conditions_match(r.conditions, attrs):
            continue
        doc_code = r.document.code if r.document else None
        param = NormParam(
            category=r.category,
            value=r.value,
            unit=r.unit,
            source=r.source,
            confidence=r.confidence,
            document_code=doc_code,
            note=r.note,
            needs_review=r.source not in ("seed", "document"),
        )
        if r.category not in out:
            out[r.category] = param
        else:
            out[r.category] = _better(out[r.category], param)
    return out


def _persist_llm_rules(
    db: Session,
    inp: BuildingInput,
    params: dict[str, NormParam],
    docs_by_code: dict[str, NormDocument],
) -> None:
    conditions = inp.discriminators()
    existing = db.scalars(
        select(NormRule).where(
            NormRule.object_type == inp.object_type, NormRule.source == "llm"
        )
    ).all()
    by_key = {(r.category, _cond_key(r.conditions)): r for r in existing}
    cond_key = _cond_key(conditions)

    for cat, p in params.items():
        if p.source != "llm":
            continue
        doc = docs_by_code.get(p.document_code) if p.document_code else None
        row = by_key.get((cat, cond_key))
        if row is not None:
            row.value = p.value
            row.unit = p.unit
            row.confidence = p.confidence
            row.note = p.note
            row.document_id = doc.id if doc else None
        else:
            db.add(
                NormRule(
                    object_type=inp.object_type,
                    category=cat,
                    value=p.value,
                    unit=p.unit,
                    conditions=conditions,
                    confidence=p.confidence,
                    source="llm",
                    note=p.note,
                    document_id=doc.id if doc else None,
                )
            )
    db.commit()


def resolve_norm_profile(
    db: Session, inp: BuildingInput, progress: ProgressFn | None = None,
    force: bool = False,
) -> NormProfile:
    """Главный вход: вернуть собранный нормативный профиль объекта.

    force=True пропускает кэш и заново обращается к LLM (нужно для «Проверить нормы»:
    подпись не зависит от demo_mode/ключа, иначе вернётся старый неподтверждённый профиль)."""
    progress = progress or _noop
    signature = inp.signature()

    # force: всегда пересобираем мимо кэша (нужно для «Проверить нормы» —
    # иначе вернётся старый неподтверждённый профиль из кэша).
    if force:
        return _build_profile(db, inp, signature, progress)

    # 1. Кэш (быстрый путь без блокировки)
    progress("norms_cache", "Поиск нормативного профиля в БД")
    cached = _cache_get(db, signature)
    if cached is not None:
        progress("norms_cache", "Профиль найден в БД (без обращения к LLM)")
        return cached

    # Сериализуем одинаковые запросы: первый делает работу и кэширует,
    # остальные дожидаются и берут результат из кэша (без дублей LLM-вызовов).
    with _lock_for(signature):
        cached = _cache_get(db, signature)
        if cached is not None:
            progress("norms_cache", "Профиль найден в БД (без обращения к LLM)")
            return cached
        return _build_profile(db, inp, signature, progress)


def _build_profile(
    db: Session, inp: BuildingInput, signature: str, progress: ProgressFn
) -> NormProfile:
    # 2. База: дефолты (всегда полный набор)
    params: dict[str, NormParam] = resolve_defaults(inp)

    # 3. Документы реестра + источники
    documents = ensure_documents(db, inp.object_type)
    docs_by_code = {d.code: d for d in documents}
    sources = [
        NormSource(
            code=d.code,
            title=d.title,
            doc_type=d.doc_type,
            url=d.url,
            status=d.status,
            confirmed=False,
        )
        for d in documents
    ]

    # 4. Правила из БД (засеянные/ранее извлечённые) поверх дефолтов
    db_params = _rules_from_db(db, inp)
    for cat, p in db_params.items():
        params[cat] = _better(params.get(cat, p), p) if cat in params else p

    # 5. LLM-извлечение (если не demo и провайдер доступен)
    if not inp.demo_mode:
        progress("norms_llm", "Извлечение норм через LLM по системному промпту РК")
        try:
            llm_params, llm_sources, web_links = extractor.extract_params(db, inp, documents)
            for cat, p in llm_params.items():
                params[cat] = _better(params.get(cat, p), p) if cat in params else p
            _persist_llm_rules(db, inp, llm_params, docs_by_code)
            # отметить подтверждённые источники
            confirmed_codes = {
                s.get("code") for s in llm_sources if s.get("confirmed")
            }
            for src in sources:
                if src.code in confirmed_codes:
                    src.confirmed = True
                    src.status = "parsed"
            for link in web_links:
                sources.append(
                    NormSource(
                        code=link.get("title", "web")[:80],
                        title=link.get("title", "web-источник"),
                        doc_type="web",
                        url=link.get("url", ""),
                        status="parsed",
                        confirmed=True,
                    )
                )
            progress("norms_llm", f"Извлечено коэффициентов: {len(llm_params)}")
        except LLMUnavailable as exc:
            progress("norms_llm", f"LLM недоступен ({exc}); расчёт по дефолтам РК")
    else:
        progress("norms_llm", "Демо-режим: нормы по дефолтам без LLM")

    profile = NormProfile(
        signature=signature,
        object_type=inp.object_type,
        params=params,
        sources=sources,
        from_cache=False,
    )

    # 6. Кэшируем собранный профиль
    _cache_put(db, profile)
    return profile
