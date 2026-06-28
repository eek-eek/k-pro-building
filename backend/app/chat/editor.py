"""Правка сметы через LLM: разбор JSON модели, слияние строк, серверный пересчёт."""
from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calc import recompute_estimate
from ..llm import get_provider
from ..llm.base import LLMUnavailable
from ..models import ChatMessage, Estimate
from ..prompts import get_prompt
from ..schemas import BuildingInput, EstimateLine, EstimateResult, to_jsonable
from ..versioning import create_version, summarize_diff

HISTORY_LIMIT = 6


class ChatUnavailable(RuntimeError):
    """Нет настроенного LLM-провайдера для чата."""


class ChatEditError(RuntimeError):
    """LLM вернул то, что нельзя применить к смете."""


def build_user_payload(result: EstimateResult, message: str,
                       history: list[ChatMessage]) -> str:
    lines = [
        {"no": l.no, "section": l.section, "title": l.title, "norm": l.norm,
         "unit": l.unit, "quantity": l.quantity, "material_price": l.material_price,
         "labor_price": l.labor_price, "machine_price": l.machine_price,
         "needs_review": l.needs_review, "comment": l.comment}
        for l in result.lines
    ]
    hist = "\n".join(f"{m.role}: {m.content}" for m in history[-HISTORY_LIMIT:])
    return (
        f"Текущая смета (строки):\n{json.dumps(lines, ensure_ascii=False)}\n\n"
        f"История диалога:\n{hist or '(пусто)'}\n\n"
        f"Просьба заказчика: {message}"
    )


def merge_and_recompute(prev: EstimateResult, inp: BuildingInput,
                        data: dict) -> tuple[EstimateResult, str]:
    """Применить JSON LLM {reply, lines, warnings_add} к prev и пересчитать на сервере."""
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ChatEditError("LLM не вернул строки сметы")
    by_no = {l.no: l for l in prev.lines}
    merged: list[EstimateLine] = []
    try:
        for raw in raw_lines:
            if not isinstance(raw, dict):
                continue
            no = str(raw.get("no", "")).strip()
            base = by_no.get(no)
            if base is not None:
                payload = base.model_dump()
                payload.update({k: v for k, v in raw.items() if v is not None})
                merged.append(EstimateLine(**payload))
            else:
                merged.append(EstimateLine(**raw))
    except (ValidationError, TypeError) as exc:
        raise ChatEditError(f"Некорректная строка от LLM: {exc}") from exc
    if not merged:
        raise ChatEditError("LLM не вернул валидных строк")
    new_result = recompute_estimate(prev, merged, inp)
    for w in data.get("warnings_add") or []:
        if isinstance(w, str) and w:
            new_result.warnings.append(w)
    reply = str(data.get("reply") or "Готово.")
    return new_result, reply


def run_chat_edit(db: Session, estimate: Estimate, message: str) -> dict:
    """Полный цикл: вызвать LLM, применить правку, создать версию и сообщения чата."""
    if estimate.current_version is None:
        raise ChatEditError("Смета ещё не рассчитана")
    provider = get_provider()
    if not provider.available:
        raise ChatUnavailable("LLM-провайдер не настроен — задайте ключ в Настройках")

    prev = EstimateResult(**estimate.current_version.result)
    inp = BuildingInput(**estimate.current_version.input)
    history = db.scalars(
        select(ChatMessage).where(ChatMessage.estimate_id == estimate.id)
        .order_by(ChatMessage.id)
    ).all()
    system = get_prompt(db, "estimate_edit")
    user = build_user_payload(prev, message, history)
    try:
        data, _sources = provider.extract_json(system, user, use_search=False)
    except LLMUnavailable as exc:
        raise ChatUnavailable(str(exc)) from exc
    if not data:
        raise ChatEditError("LLM вернул пустой/некорректный ответ")

    new_result, reply = merge_and_recompute(prev, inp, data)
    summary = summarize_diff(prev, new_result)
    db.add(ChatMessage(estimate_id=estimate.id, role="user", content=message))
    version = create_version(db, estimate, inp, new_result,
                             source="llm_edit", summary=summary)
    db.add(ChatMessage(estimate_id=estimate.id, role="assistant",
                       content=reply, version_id=version.id))
    db.commit()
    return {"reply": reply, "version_number": version.version_number,
            "result": to_jsonable(new_result)}
