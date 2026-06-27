# YBC v0.2 — Plan 2: AI Chat Editor (backend)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let a user edit a calculated estimate by chatting with the LLM ("убери раздел кровли", "пересчитай арматуру по 100 кг/м³"); the backend applies the change as a new `llm_edit` version and stores the conversation.

**Architecture:** A `chat/editor.py` module builds the LLM payload from the current `EstimateResult`, gets the model's revised line list as strict JSON, MERGES it onto the previous lines by `no`, then runs the existing server-authoritative `recompute_estimate` — the model never computes money. Two endpoints expose chat history and posting a message. The POST route is a **sync** FastAPI handler (runs in the threadpool, so the blocking provider call never blocks the event loop and the request DB session stays on one thread). Builds entirely on Plan 1 (`recompute_estimate`, `create_version`, `summarize_diff`, `ChatMessage`, prompt store).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, Pydantic v2, pytest. Spec: `docs/superpowers/specs/2026-06-27-yale-building-calculator-v02-design.md` §6.

**Run tests:** `cd backend && .venv/bin/python -m pytest -q`.

---

## File Structure
- `backend/app/chat/__init__.py` — **create** (package marker exposing the public funcs).
- `backend/app/chat/editor.py` — **create**: `ChatUnavailable`, `ChatEditError`, `build_user_payload`, `merge_and_recompute`, `run_chat_edit`.
- `backend/app/api/routes.py` — **modify**: GET/POST `/estimates/{id}/chat`.
- `backend/app/schemas.py` — **modify**: `ChatPost` request model.
- `backend/tests/test_chat_editor.py` — **create**: pure merge/recompute unit tests.
- `backend/tests/test_chat_api.py` — **create**: endpoint tests with a fake provider.

---

## Task 1: Chat editor module

**Files:** Create `backend/app/chat/__init__.py`, `backend/app/chat/editor.py`; test `backend/tests/test_chat_editor.py`.

Context: `get_provider()` (from `app.llm`) returns the configured provider; it has `.available: bool` and `.extract_json(system, user, *, use_search=False) -> tuple[dict, list]` (raises `LLMUnavailable` on failure). `recompute_estimate(prev, lines, inp)`, `create_version`, `summarize_diff` exist. `EstimateLine`/`EstimateResult`/`BuildingInput` are Pydantic v2 models. `get_prompt(db, "estimate_edit")` returns the system prompt. `ChatMessage(estimate_id, role, content, version_id)` model exists.

- [ ] **Step 1: Write failing unit test** `backend/tests/test_chat_editor.py`:
```python
import pytest
from app.chat.editor import merge_and_recompute, ChatEditError
from app.schemas import BuildingInput, EstimateLine, EstimateResult, EstimateTotals


def _line(no, qty, mat):
    return EstimateLine(no=no, section="Земляные работы", title="t", unit="м³",
                        quantity=qty, material_price=mat, total=round(qty * mat))


def _prev():
    lines = [_line("2.1", 10, 100), _line("2.2", 5, 200)]
    return EstimateResult(project_name="p", city="c", object_type="o", lines=lines,
                          section_totals={"Земляные работы": 2000},
                          totals=EstimateTotals(grand_total=2000), warnings=["w0"])


def test_merge_applies_partial_line_update_and_recomputes():
    prev = _prev()
    inp = BuildingInput(overhead_pct=0, contingency_pct=0, vat_pct=0)
    # LLM returns only `no` + a new quantity for one line, full list of two lines
    data = {"reply": "ок", "lines": [{"no": "2.1", "quantity": 20}, {"no": "2.2"}],
            "warnings_add": ["проверьте объём"]}
    result, reply = merge_and_recompute(prev, inp, data)
    assert reply == "ок"
    l21 = next(l for l in result.lines if l.no == "2.1")
    assert l21.quantity == 20
    assert l21.total == 2000  # 20 * 100, recomputed server-side
    assert l21.title == "t"   # preserved from prev (partial update merged)
    assert result.totals.grand_total == 3000  # 2000 + 1000
    assert "проверьте объём" in result.warnings


def test_merge_rejects_empty_lines():
    prev = _prev()
    inp = BuildingInput()
    with pytest.raises(ChatEditError):
        merge_and_recompute(prev, inp, {"reply": "x", "lines": []})


def test_merge_rejects_garbage_line():
    prev = _prev()
    inp = BuildingInput()
    with pytest.raises(ChatEditError):
        # a brand-new line missing required fields (no section/unit) -> validation error
        merge_and_recompute(prev, inp, {"lines": [{"no": "9.9", "quantity": "abc"}]})
```

- [ ] **Step 2: Run, confirm FAIL** (`ModuleNotFoundError: app.chat`):
`cd backend && .venv/bin/python -m pytest tests/test_chat_editor.py -v`

- [ ] **Step 3: Create `backend/app/chat/__init__.py`:**
```python
"""Чат-редактор сметы через LLM."""

from .editor import ChatEditError, ChatUnavailable, run_chat_edit

__all__ = ["ChatEditError", "ChatUnavailable", "run_chat_edit"]
```

- [ ] **Step 4: Create `backend/app/chat/editor.py`:**
```python
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
        {"no": l.no, "section": l.section, "title": l.title, "unit": l.unit,
         "quantity": l.quantity, "material_price": l.material_price,
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
```

- [ ] **Step 5: Run unit tests (expect 3 passed), then full suite (all green):**
`cd backend && .venv/bin/python -m pytest tests/test_chat_editor.py -v`
`cd backend && .venv/bin/python -m pytest -q`

- [ ] **Step 6: Commit:**
```bash
git add backend/app/chat/ backend/tests/test_chat_editor.py
git commit -m "feat(chat): LLM estimate editor — merge lines + server recompute"
```

---

## Task 2: Chat endpoints

**Files:** Modify `backend/app/api/routes.py`, `backend/app/schemas.py`; test `backend/tests/test_chat_api.py`.

- [ ] **Step 1: Write failing test** `backend/tests/test_chat_api.py`:
```python
import app.chat.editor as editor
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class _FakeProvider:
    available = True
    def extract_json(self, system, user, *, use_search=False):
        # echo back the same lines but drop one (simulate "remove a section")
        import json as _j
        # parse the lines block out of the user payload
        start = user.index("[")
        end = user.index("]", start) + 1
        lines = _j.loads(user[start:end])
        kept = lines[:-1]  # remove the last line
        return {"reply": "Убрал последнюю строку.", "lines": kept}, []


def _calc():
    return client.post("/api/estimate/sync", json={
        "object_type": "Жилой дом", "demo_mode": True, "use_search": False}).json()["estimate_id"]


def test_chat_unavailable_returns_409(monkeypatch):
    eid = _calc()
    # demo provider is unavailable by default
    r = client.post(f"/api/estimates/{eid}/chat", json={"message": "убери кровлю"})
    assert r.status_code == 409


def test_chat_edit_creates_version_and_messages(monkeypatch):
    eid = _calc()
    monkeypatch.setattr(editor, "get_provider", lambda: _FakeProvider())
    r = client.post(f"/api/estimates/{eid}/chat", json={"message": "убери последнюю строку"})
    assert r.status_code == 200
    body = r.json()
    assert body["version_number"] == 2
    assert body["reply"]
    msgs = client.get(f"/api/estimates/{eid}/chat").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
```

- [ ] **Step 2: Run, confirm FAIL** (404 — no chat endpoints):
`cd backend && .venv/bin/python -m pytest tests/test_chat_api.py -v`

- [ ] **Step 3: Add schema to `backend/app/schemas.py`:**
```python
class ChatPost(BaseModel):
    message: str
```

- [ ] **Step 4: Add endpoints to `backend/app/api/routes.py`.** Add imports near the top: `from ..chat import run_chat_edit, ChatUnavailable, ChatEditError` and add `ChatPost` to the schemas import. Then append:
```python
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
             "version_number": vmap.get(m.version_id) if m.version_id else None,
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
```

- [ ] **Step 5: Run the chat-api test (expect 2 passed), then full suite (all green):**
`cd backend && .venv/bin/python -m pytest tests/test_chat_api.py -v`
`cd backend && .venv/bin/python -m pytest -q`

- [ ] **Step 6: Commit:**
```bash
git add backend/app/api/routes.py backend/app/schemas.py backend/tests/test_chat_api.py
git commit -m "feat(api): estimate chat endpoints (list + post, 409/422 errors)"
```

---

## Self-Review notes (author)
- **Spec §6 coverage:** estimate_edit prompt (seeded in Plan 1) → used in `run_chat_edit`; strict-JSON parse via provider.extract_json; merge-by-`no` so partial line updates don't fail validation → Task 1; server recompute (no LLM money) → reuses `recompute_estimate`; new `llm_edit` version + user/assistant ChatMessages → Task 1; provider-unavailable → 409, bad output → 422 → Task 2; chat history endpoint → Task 2.
- **Async/offload:** the spec said `asyncio.to_thread`; this plan uses a **sync** route instead (FastAPI runs it in the anyio threadpool — same non-blocking effect, and avoids sharing the request Session across threads). Documented deviation.
- **Type consistency:** `run_chat_edit(db, estimate, message)`, `merge_and_recompute(prev, inp, data)` used consistently; source value `llm_edit` matches the model enum; `ChatMessage(estimate_id, role, content, version_id)` matches Plan 1 schema.
- **Failure safety:** on ChatUnavailable/ChatEditError nothing is committed (no version, no messages) — previous estimate untouched.
```
