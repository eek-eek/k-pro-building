# YBC v0.2 — Plan 1: Backend Foundation (Versioned Estimates + Integrity + CRUD)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn estimates into first-class, versioned entities with a server-authoritative recompute engine and a full CRUD/versioning REST API — the foundation the AI chat (Plan 2), settings (Plan 3), and redesigned frontend (Plan 4) build on.

**Architecture:** Refactor the flat `Estimate` table into a container + immutable `EstimateVersion` snapshots; add `ChatMessage`, `Prompt`, `AppSetting` tables. A pure `recompute_estimate()` reproduces `build_estimate()` math byte-for-byte so edits never drift. All calc/version writes happen in the caller (job manager / routes), keeping `build_estimate` and existing tests intact.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (SQLite), Pydantic v2, pytest. Spec: `docs/superpowers/specs/2026-06-27-yale-building-calculator-v02-design.md`.

**Run tests with:** `cd backend && .venv/bin/python -m pytest -q` (venv is on Python 3.11).

---

## File Structure

- `backend/app/database.py` — **modify**: add `PRAGMA foreign_keys=ON` connect listener.
- `backend/app/models.py` — **modify**: refactor `Estimate`; add `EstimateVersion`, `ChatMessage`, `Prompt`, `AppSetting`.
- `backend/app/calc/estimate.py` — **modify**: extract `recompute_estimate()`.
- `backend/app/calc/__init__.py` — **modify**: export `recompute_estimate`.
- `backend/app/versioning.py` — **create**: `next_version_number`, `create_version`, `summarize_diff`.
- `backend/app/prompts.py` — **create**: `PROMPT_DEFAULTS`, `get_prompt`, `seed_prompts`.
- `backend/app/norms/extractor.py` — **modify**: read `get_prompt("norm_extraction")` instead of module constant.
- `backend/app/jobs/manager.py` — **modify**: accept `estimate_id`; write `EstimateVersion` + pointer instead of flat `Estimate`.
- `backend/app/api/routes.py` — **modify**: estimate CRUD, calc, versions, rollback, manual-edit endpoints.
- `backend/app/schemas.py` — **modify**: request/response models for the new endpoints.
- `backend/app/seed.py` — **modify**: call `seed_prompts`.
- `backend/tests/test_recompute.py` — **create**: golden + manual-edit math tests.
- `backend/tests/test_versioning.py` — **create**: version-number + summary tests.
- `backend/tests/test_estimates_api.py` — **create**: CRUD + calc + versions + rollback + manual-edit API tests.

---

## Task 1: Enable SQLite foreign-key enforcement

**Files:**
- Modify: `backend/app/database.py`
- Test: `backend/tests/test_recompute.py` (temporary location for this one assertion; lives with DB tests)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_db_pragma.py`:

```python
from sqlalchemy import text
from app.database import engine


def test_foreign_keys_pragma_on():
    with engine.connect() as conn:
        val = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert val == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db_pragma.py -v`
Expected: FAIL (`assert 0 == 1`).

- [ ] **Step 3: Add the connect listener**

In `backend/app/database.py`, after the `engine = create_engine(...)` block, add:

```python
from sqlalchemy import event


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _connection_record):
    """SQLite ignores FK constraints unless enabled per connection."""
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db_pragma.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/database.py backend/tests/test_db_pragma.py
git commit -m "feat(db): enable SQLite foreign_keys PRAGMA per connection"
```

---

## Task 2: Reconciled ORM models

**Files:**
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_versioning.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_versioning.py`:

```python
import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models  # registers all tables


def _mem_session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def test_estimate_version_chain_persists():
    db = _mem_session()
    est = models.Estimate(name="T", object_type="Жилой дом", city="Алматы")
    db.add(est)
    db.flush()
    v = models.EstimateVersion(
        estimate_id=est.id, version_number=1, input={}, result={},
        total=100.0, source="initial", summary="",
    )
    db.add(v)
    db.flush()
    est.current_version_id = v.id
    msg = models.ChatMessage(estimate_id=est.id, role="user", content="hi")
    db.add(msg)
    db.commit()
    assert est.current_version_id == v.id
    assert est.versions[0].version_number == 1
    assert est.chat_messages[0].content == "hi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_versioning.py -v`
Expected: FAIL (`AttributeError`/`TypeError` — `Estimate` has no `name`, no `versions`).

- [ ] **Step 3: Replace the `Estimate` class and add the new models**

In `backend/app/models.py`, add `ForeignKey`/`Boolean`/`UniqueConstraint` to the imports line if missing:

```python
from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
```

Replace the existing `class Estimate(Base): ...` block with:

```python
class Estimate(Base):
    """Container for a versioned estimate project."""

    __tablename__ = "estimates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    object_type: Mapped[str] = mapped_column(String(64), index=True, default="")
    city: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimate_versions.id", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    versions: Mapped[list["EstimateVersion"]] = relationship(
        back_populates="estimate",
        cascade="all, delete-orphan",
        order_by="EstimateVersion.version_number",
        foreign_keys="EstimateVersion.estimate_id",
    )
    chat_messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="estimate",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )
    current_version: Mapped["EstimateVersion | None"] = relationship(
        "EstimateVersion", foreign_keys=[current_version_id], post_update=True
    )


class EstimateVersion(Base):
    """Immutable snapshot of an estimate at one point in time."""

    __tablename__ = "estimate_versions"
    __table_args__ = (UniqueConstraint("estimate_id", "version_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, index=True)
    input: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16), index=True)  # initial|llm_edit|manual_edit|rollback
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    estimate: Mapped["Estimate"] = relationship(
        back_populates="versions", foreign_keys=[estimate_id]
    )


class ChatMessage(Base):
    """One chat turn inside an estimate."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimate_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    estimate: Mapped["Estimate"] = relationship(back_populates="chat_messages")


class Prompt(Base):
    """Editable system prompt, seeded from code defaults."""

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class AppSetting(Base):
    """Key-value runtime setting overriding .env (empty value = unset)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
```

(`Any` is already imported at the top of the file; `_utcnow` already exists.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_versioning.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_versioning.py
git commit -m "feat(models): versioned estimate schema (Estimate/Version/Chat/Prompt/AppSetting)"
```

---

## Task 3: `recompute_estimate` — server-authoritative math

**Files:**
- Modify: `backend/app/calc/estimate.py`, `backend/app/calc/__init__.py`
- Test: `backend/tests/test_recompute.py`

- [ ] **Step 1: Write the failing golden test**

Create `backend/tests/test_recompute.py`:

```python
from app.calc import build_estimate, recompute_estimate
from app.norms.resolver import resolve_norm_profile
from app.schemas import BuildingInput
from app.database import SessionLocal
from app.seed import run_seed


def _result():
    run_seed()
    db = SessionLocal()
    try:
        inp = BuildingInput(object_type="Жилой дом", demo_mode=True, use_search=False)
        profile = resolve_norm_profile(db, inp)
        return inp, build_estimate(db, inp, profile)
    finally:
        db.close()


def test_recompute_is_noop_on_unedited_estimate():
    inp, res = _result()
    again = recompute_estimate(res, [l.model_copy(deep=True) for l in res.lines], inp)
    assert [l.total for l in again.lines] == [l.total for l in res.lines]
    assert again.section_totals == res.section_totals
    assert again.totals.model_dump() == res.totals.model_dump()


def test_recompute_overwrites_bogus_line_total():
    inp, res = _result()
    lines = [l.model_copy(deep=True) for l in res.lines]
    # find a non-prep line and corrupt its total
    target = next(l for l in lines if l.no != "1.1")
    target.total = 999999999
    out = recompute_estimate(res, lines, inp)
    fixed = next(l for l in out.lines if l.no == target.no)
    assert fixed.total == round(
        fixed.quantity * (fixed.material_price + fixed.labor_price + fixed.machine_price)
    )


def test_recompute_carries_forward_warnings_and_sources():
    inp, res = _result()
    out = recompute_estimate(res, [l.model_copy(deep=True) for l in res.lines], inp)
    assert out.warnings == res.warnings
    assert out.precision_class == res.precision_class
    assert len(out.volumes) == len(res.volumes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_recompute.py -v`
Expected: FAIL (`ImportError: cannot import name 'recompute_estimate'`).

- [ ] **Step 3: Implement `recompute_estimate`**

In `backend/app/calc/estimate.py`, add the constant near the top (after `SECTIONS`):

```python
PREP_TITLE = "Подготовительные работы и временные сооружения"
```

Append this function at the end of the file:

```python
def recompute_estimate(
    prev: EstimateResult, lines: list[EstimateLine], inp: BuildingInput
) -> EstimateResult:
    """Recompute all money from `lines` (server-authoritative), preserving
    non-line context from `prev`. Mirrors build_estimate() rounding exactly."""
    core = [ln for ln in lines if ln.no != "1.1" and ln.section != PREP_TITLE]
    prep_existing = [ln for ln in lines if ln.no == "1.1" or ln.section == PREP_TITLE]

    section_totals: dict[str, float] = {}
    direct_core = 0.0
    rebuilt: list[EstimateLine] = []
    for ln in core:
        unit_cost = ln.material_price + ln.labor_price + ln.machine_price
        ln.total = round(ln.quantity * unit_cost)
        rebuilt.append(ln)
        section_totals[ln.section] = round(section_totals.get(ln.section, 0.0) + ln.total)
        direct_core += ln.total

    final_lines: list[EstimateLine] = []
    if prep_existing:
        prep_total = round(direct_core * 0.015)
        if prep_total > 0:
            prep = prep_existing[0]
            prep.no = "1.1"
            prep.section = PREP_TITLE
            prep.title = "Подготовительные работы и временные сооружения"
            prep.unit = "усл."
            prep.quantity = 1
            prep.material_price = 0.0
            prep.labor_price = prep_total
            prep.machine_price = 0.0
            prep.total = prep_total
            section_totals[PREP_TITLE] = prep_total
            direct_core += prep_total
            final_lines.append(prep)
    final_lines.extend(rebuilt)

    direct = round(direct_core)
    overhead = round(direct * inp.overhead_pct / 100)
    subtotal1 = direct + overhead
    contingency = round(subtotal1 * inp.contingency_pct / 100)
    subtotal2 = subtotal1 + contingency
    vat = round(subtotal2 * inp.vat_pct / 100)
    grand = subtotal2 + vat

    totals = EstimateTotals(
        direct=direct, overhead=overhead, overhead_pct=inp.overhead_pct,
        subtotal_with_overhead=subtotal1, contingency=contingency,
        contingency_pct=inp.contingency_pct, subtotal_with_contingency=subtotal2,
        vat=vat, vat_pct=inp.vat_pct, grand_total=grand,
    )
    return EstimateResult(
        project_name=prev.project_name, city=prev.city, object_type=prev.object_type,
        precision_class=prev.precision_class, warnings=prev.warnings,
        sources=prev.sources, volumes=prev.volumes, lines=final_lines,
        section_totals=section_totals, totals=totals,
        contractor_questions=prev.contractor_questions,
        clarifications=prev.clarifications,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        llm_narrative=prev.llm_narrative,
    )
```

Then in `backend/app/calc/__init__.py`:

```python
"""Детерминированный расчёт: геометрия → объёмы → смета."""

from .estimate import build_estimate, recompute_estimate

__all__ = ["build_estimate", "recompute_estimate"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_recompute.py -v`
Expected: PASS (3 passed). Also run the existing suite to confirm nothing broke: `cd backend && .venv/bin/python -m pytest -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/calc/estimate.py backend/app/calc/__init__.py backend/tests/test_recompute.py
git commit -m "feat(calc): server-authoritative recompute_estimate with golden round-trip test"
```

---

## Task 4: Versioning service

**Files:**
- Create: `backend/app/versioning.py`
- Test: `backend/tests/test_versioning.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_versioning.py`:

```python
from app.versioning import create_version, next_version_number, summarize_diff
from app.schemas import BuildingInput, EstimateResult, EstimateTotals, EstimateLine


def _line(no, total):
    return EstimateLine(no=no, section="S", title="t", unit="м³", quantity=1,
                        material_price=total, total=total)


def _res(lines):
    return EstimateResult(project_name="p", city="c", object_type="o", lines=lines,
                          totals=EstimateTotals(grand_total=sum(l.total for l in lines)))


def test_next_version_number_increments_per_estimate():
    db = _mem_session()
    est = models.Estimate(name="T")
    db.add(est); db.flush()
    assert next_version_number(db, est.id) == 1
    db.add(models.EstimateVersion(estimate_id=est.id, version_number=1, input={},
                                  result={}, total=0, source="initial"))
    db.flush()
    assert next_version_number(db, est.id) == 2


def test_create_version_sets_pointer_and_fields():
    db = _mem_session()
    est = models.Estimate(name="T")
    db.add(est); db.flush()
    res = _res([_line("2.1", 100)])
    v = create_version(db, est, BuildingInput(), res, source="initial", summary="x")
    db.commit()
    assert v.version_number == 1
    assert est.current_version_id == v.id
    assert v.total == 100


def test_summarize_diff_reports_line_and_total_delta():
    prev = _res([_line("2.1", 100), _line("3.1", 200)])
    new = _res([_line("2.1", 100)])
    s = summarize_diff(prev, new)
    assert "1" in s  # one line removed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_versioning.py -v`
Expected: FAIL (`ModuleNotFoundError: app.versioning`).

- [ ] **Step 3: Implement the service**

Create `backend/app/versioning.py`:

```python
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
        db.add(version)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_versioning.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/versioning.py backend/tests/test_versioning.py
git commit -m "feat(versioning): create_version, next_version_number, summarize_diff"
```

---

## Task 5: Prompt store + extractor read-through

**Files:**
- Create: `backend/app/prompts.py`
- Modify: `backend/app/norms/extractor.py`, `backend/app/seed.py`
- Test: `backend/tests/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_prompts.py`:

```python
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


def test_get_prompt_falls_back_to_code_default_when_missing():
    db = SessionLocal()
    try:
        # unknown key returns "" ; known key returns code default even if DB empty
        assert get_prompt(db, "estimate_edit")  # non-empty code default
    finally:
        db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_prompts.py -v`
Expected: FAIL (`ModuleNotFoundError: app.prompts`).

- [ ] **Step 3: Implement the prompt store**

Create `backend/app/prompts.py`:

```python
"""Code-default system prompts + DB read-through with reset support."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Prompt
from .norms.extractor import SYSTEM_PROMPT as NORM_EXTRACTION_PROMPT

ESTIMATE_EDIT_PROMPT = """Ты — помощник-сметчик Республики Казахстан. На вход даётся
текущая смета (разделы и строки) и просьба заказчика изменить её.

Каждая строка имеет поля: no, section, title, norm, unit, quantity,
material_price, labor_price, machine_price, needs_review, comment.

Жёсткие правила:
- Верни СТРОГО один JSON-объект и ничего вокруг.
- Формат: {"reply": "<короткий ответ заказчику по-русски>",
  "lines": [<полный изменённый список строк со ВСЕМИ полями>],
  "warnings_add": ["<новое предупреждение>"]}.
- Возвращай ВЕСЬ список строк, а не только изменённые.
- НЕ считай итоги, разделы и total строк — это делает система.
- НЕ выдумывай нормы; спорное помечай "needs_review": true и поясняй в "comment".
- Сохраняй схему строки точно (те же имена полей)."""

PROMPT_DEFAULTS: dict[str, dict[str, str]] = {
    "norm_extraction": {
        "title": "Извлечение норм РК",
        "description": "Используется при расчёте сметы (резолвер норм).",
        "body": NORM_EXTRACTION_PROMPT,
    },
    "estimate_edit": {
        "title": "Редактирование сметы (чат)",
        "description": "Используется в чате карточки сметы.",
        "body": ESTIMATE_EDIT_PROMPT,
    },
}


def seed_prompts(db: Session) -> None:
    existing = {p.key for p in db.scalars(select(Prompt)).all()}
    for key, meta in PROMPT_DEFAULTS.items():
        if key not in existing:
            db.add(Prompt(key=key, title=meta["title"],
                          description=meta["description"], body=meta["body"],
                          is_custom=False))
    db.commit()


def get_prompt(db: Session, key: str) -> str:
    """DB body if present, else the code default, else empty string."""
    row = db.scalar(select(Prompt).where(Prompt.key == key))
    if row and row.body:
        return row.body
    default = PROMPT_DEFAULTS.get(key)
    return default["body"] if default else ""
```

In `backend/app/seed.py`, add the import and call inside `run_seed()`:

```python
from .prompts import seed_prompts
```
and inside the `with SessionLocal() as db:` block, after `seed_prices(db)`:
```python
        seed_prompts(db)
```

In `backend/app/norms/extractor.py`, change `extract_params` to read the prompt from DB. It already receives no `db`; thread one through. Replace the function signature and the `provider.extract_json(...)` call:

```python
def extract_params(
    db, inp: BuildingInput, documents: list[tuple]
) -> tuple[dict[str, NormParam], list[dict], list[dict]]:
    from ..prompts import get_prompt  # local import avoids circular import
    provider = get_provider()
    if not provider.available:
        raise LLMUnavailable(f"Провайдер {provider.name} недоступен")
    system = get_prompt(db, "norm_extraction") or SYSTEM_PROMPT
    user = build_user_prompt(inp, documents)
    data, web_links = provider.extract_json(system, user, use_search=inp.use_search)
    # ... rest unchanged ...
```

Then update the single caller in `backend/app/norms/resolver.py` (the `extractor.extract_params(inp, documents)` call) to pass `db`: `extractor.extract_params(db, inp, documents)`. The resolver already has `db` in scope (`resolve_norm_profile(db, ...)`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_prompts.py -v`
Then full suite: `cd backend && .venv/bin/python -m pytest -q` (confirm `test_resolver.py` still passes — the demo path raises `LLMUnavailable` before the prompt is used, so behavior is unchanged).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts.py backend/app/seed.py backend/app/norms/extractor.py backend/app/norms/resolver.py backend/tests/test_prompts.py
git commit -m "feat(prompts): DB-backed prompt store seeded from code defaults"
```

---

## Task 6: Wire job manager + sync route to versioned schema

**Files:**
- Modify: `backend/app/jobs/manager.py`, `backend/app/api/routes.py`
- Test: covered by `test_estimates_api.py` (Task 7) + a sync smoke here

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_sync_calc.py`:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_sync_calc_creates_estimate_with_initial_version():
    r = client.post("/api/estimate/sync", json={
        "object_type": "Жилой дом", "demo_mode": True, "use_search": False,
    })
    assert r.status_code == 200
    body = r.json()
    # response carries the new estimate id and version 1
    assert body["estimate_id"] >= 1
    assert body["version_number"] == 1
    assert body["result"]["totals"]["grand_total"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_sync_calc.py -v`
Expected: FAIL (current sync route returns a bare `EstimateResult`, no `estimate_id`/`version_number`).

- [ ] **Step 3: Update the job manager**

In `backend/app/jobs/manager.py`:

Change `create` to accept and store an `estimate_id`, and `start`/`_run`/`_execute` to thread it through:

```python
    def create(self, estimate_id: int) -> JobRuntime:
        job_id = str(uuid.uuid4())
        steps = [JobStep(key=k, label=l) for k, l in STEP_DEFS]
        runtime = JobRuntime(id=job_id, steps=steps, estimate_id=estimate_id)
        self._jobs[job_id] = runtime
        with SessionLocal() as db:
            db.add(Job(id=job_id, status="pending", steps=to_jsonable(steps),
                       estimate_id=estimate_id))
            db.commit()
        return runtime
```

```python
    async def start(self, runtime: JobRuntime, inp: BuildingInput) -> None:
        runtime.loop = asyncio.get_running_loop()
        runtime.status = "running"
        asyncio.create_task(self._run(runtime, inp))
```
(unchanged, but `_execute` now uses `runtime.estimate_id`).

Replace the persistence block in `_execute` (the `est = Estimate(...) ... db.commit()` part) with version creation:

```python
            self._set_step(runtime, "estimate", "running")
            result = build_estimate(db, inp, profile)
            self._set_step(runtime, "estimate", "done")

            from ..versioning import create_version
            estimate = db.get(Estimate, runtime.estimate_id)
            version = create_version(db, estimate, inp, result, source="initial")
            db.commit()
            runtime.estimate_id = estimate.id
            runtime.result = result
            runtime.status = "done"
            self._set_step(runtime, "done", "done")
```

(Leave the `Job` row update below it intact; `job_row.estimate_id = est.id` becomes `job_row.estimate_id = runtime.estimate_id`.)

- [ ] **Step 4: Update the sync route**

In `backend/app/api/routes.py`, rewrite `create_estimate_sync` to create a container + initial version and return ids. Replace its body:

```python
@router.post("/estimate/sync")
def create_estimate_sync(inp: BuildingInput, db: Session = Depends(get_db)) -> dict:
    """Synchronous calc — creates an Estimate container + initial version."""
    from ..versioning import create_version
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
```

(Remove the old `response_model=EstimateResult` decorator argument and the old `Estimate(input=..., result=..., total=...)` code. Keep the existing imports; `EstimateResult` import may become unused — leave it, it is used by JobStatus.)

- [ ] **Step 5: Run + commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_sync_calc.py tests/test_recompute.py -v`
Expected: PASS.

```bash
git add backend/app/jobs/manager.py backend/app/api/routes.py backend/tests/test_sync_calc.py
git commit -m "feat(calc): job + sync route write Estimate container + initial version"
```

---

## Task 7: Estimate CRUD + calc endpoints

**Files:**
- Modify: `backend/app/api/routes.py`, `backend/app/schemas.py`
- Test: `backend/tests/test_estimates_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_estimates_api.py`:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
DRAFT = {"name": "Тестовый дом", "input": {"object_type": "Жилой дом",
         "demo_mode": True, "use_search": False}}


def test_create_list_get_patch_delete_estimate():
    cid = client.post("/api/estimates", json=DRAFT).json()["id"]
    listing = client.get("/api/estimates").json()
    assert any(c["id"] == cid and c["status"] == "draft" for c in listing)

    got = client.get(f"/api/estimates/{cid}").json()
    assert got["estimate"]["name"] == "Тестовый дом"

    client.patch(f"/api/estimates/{cid}", json={"name": "Новое имя"})
    assert client.get(f"/api/estimates/{cid}").json()["estimate"]["name"] == "Новое имя"

    assert client.delete(f"/api/estimates/{cid}").status_code == 204
    assert client.get(f"/api/estimates/{cid}").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_estimates_api.py -v`
Expected: FAIL (404 — endpoints don't exist).

- [ ] **Step 3: Add schemas**

In `backend/app/schemas.py`, add near the other models:

```python
class EstimateCard(BaseModel):
    id: int
    name: str
    object_type: str
    city: str
    status: str
    total: float
    version_count: int
    message_count: int
    updated_at: str


class EstimateCreate(BaseModel):
    name: str = ""
    input: Optional[BuildingInput] = None


class EstimatePatch(BaseModel):
    name: Optional[str] = None
    input: Optional[BuildingInput] = None
```

- [ ] **Step 4: Add the endpoints**

In `backend/app/api/routes.py`, add imports at the top:

```python
from ..models import Estimate, EstimateVersion, ChatMessage, NormDocument, PriceItem
from ..schemas import (
    BuildingInput, EstimateResult, JobStatus, to_jsonable,
    EstimateCard, EstimateCreate, EstimatePatch,
)
```

Append these endpoints:

```python
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
def delete_estimate(estimate_id: int, db: Session = Depends(get_db)) -> None:
    est = db.get(Estimate, estimate_id)
    if est is None:
        raise HTTPException(status_code=404, detail="estimate not found")
    # break the self-FK before delete so SET NULL/cascade is clean
    est.current_version_id = None
    db.flush()
    db.delete(est)
    db.commit()
```

Add the calc-within-estimate endpoint (reuses the SSE job flow):

```python
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
```

Also update the legacy `POST /api/estimate` (`create_estimate`) to create a container first:

```python
@router.post("/estimate")
async def create_estimate(inp: BuildingInput, db: Session = Depends(get_db)) -> dict:
    est = Estimate(name=inp.project_name, object_type=inp.object_type, city=inp.city)
    db.add(est)
    db.commit()
    runtime = job_manager.create(est.id)
    await job_manager.start(runtime, inp)
    return {"job_id": runtime.id, "estimate_id": est.id}
```

- [ ] **Step 5: Run + commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_estimates_api.py -v`
Expected: PASS.

```bash
git add backend/app/api/routes.py backend/app/schemas.py backend/tests/test_estimates_api.py
git commit -m "feat(api): estimate CRUD + calc-within-estimate endpoints"
```

---

## Task 8: Versions, rollback, manual-edit endpoints

**Files:**
- Modify: `backend/app/api/routes.py`, `backend/app/schemas.py`
- Test: `backend/tests/test_estimates_api.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_estimates_api.py`:

```python
def _calculated_estimate():
    body = client.post("/api/estimate/sync", json={
        "object_type": "Жилой дом", "demo_mode": True, "use_search": False}).json()
    return body["estimate_id"]


def test_versions_manual_edit_and_rollback():
    eid = _calculated_estimate()
    v1 = client.get(f"/api/estimates/{eid}").json()["current_version"]
    lines = v1["result"]["lines"]

    # manual edit: bump a non-prep line quantity, expect a new version + recompute
    target = next(l for l in lines if l["no"] != "1.1")
    target["quantity"] = target["quantity"] + 10
    r = client.post(f"/api/estimates/{eid}/manual-edit", json={"lines": lines})
    assert r.status_code == 200
    assert r.json()["version_number"] == 2

    versions = client.get(f"/api/estimates/{eid}/versions").json()
    assert [v["version_number"] for v in versions] == [1, 2]

    # rollback to v1 creates v3 cloning v1's totals
    r = client.post(f"/api/estimates/{eid}/rollback", json={"version_number": 1})
    assert r.json()["version_number"] == 3
    cur = client.get(f"/api/estimates/{eid}").json()["current_version"]
    assert cur["result"]["totals"]["grand_total"] == v1["result"]["totals"]["grand_total"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_estimates_api.py::test_versions_manual_edit_and_rollback -v`
Expected: FAIL (404).

- [ ] **Step 3: Add schemas**

In `backend/app/schemas.py`:

```python
class ManualEditRequest(BaseModel):
    lines: list[EstimateLine]
    input: Optional[BuildingInput] = None


class RollbackRequest(BaseModel):
    version_number: int
```

- [ ] **Step 4: Add the endpoints**

In `backend/app/api/routes.py` add to imports: `from ..schemas import ManualEditRequest, RollbackRequest` (merge into the existing schema import line) and `from ..calc import build_estimate, recompute_estimate`. Append:

```python
@router.get("/estimates/{estimate_id}/versions")
def list_versions(estimate_id: int, db: Session = Depends(get_db)) -> list[dict]:
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
    from ..versioning import create_version, summarize_diff
    est = db.get(Estimate, estimate_id)
    if est is None or est.current_version is None:
        raise HTTPException(status_code=404, detail="estimate not calculated")
    prev = EstimateResult(**est.current_version.result)
    inp = body.input or BuildingInput(**est.current_version.input)
    new_result = recompute_estimate(prev, body.lines, inp)
    summary = summarize_diff(prev, new_result)
    version = create_version(db, est, inp, new_result, source="manual_edit", summary=summary)
    db.commit()
    return {"version_number": version.version_number, "result": to_jsonable(new_result)}


@router.post("/estimates/{estimate_id}/rollback")
def rollback(estimate_id: int, body: RollbackRequest,
             db: Session = Depends(get_db)) -> dict:
    from ..versioning import create_version
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
```

- [ ] **Step 5: Run + commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_estimates_api.py -v` then full suite `cd backend && .venv/bin/python -m pytest -q`.
Expected: all PASS.

```bash
git add backend/app/api/routes.py backend/app/schemas.py backend/tests/test_estimates_api.py
git commit -m "feat(api): versions list/get, manual-edit recompute, rollback"
```

---

## Task 9: Remove the stale `get_estimate` route + full regression

**Files:**
- Modify: `backend/app/api/routes.py`
- Test: full suite

- [ ] **Step 1:** Delete the old `@router.get("/estimates/{estimate_id}")` handler named `get_estimate` that returned `{"id","total","result"}` (now superseded by `get_estimate_full`). Confirm only one route maps to `GET /estimates/{estimate_id}`.

- [ ] **Step 2: Run the full suite**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: all pass (existing `test_calc.py`, `test_resolver.py` + new tests).

- [ ] **Step 3: Manual smoke (migration on fresh DB)**

```bash
cd backend && rm -f data/ai_smeta.db
.venv/bin/python -c "from app.seed import run_seed; run_seed(); print('seed ok')"
.venv/bin/python -m uvicorn app.main:app --port 8000 &
sleep 2
curl -s -X POST localhost:8000/api/estimate/sync -H 'Content-Type: application/json' \
  -d '{"object_type":"Жилой дом","demo_mode":true,"use_search":false}' | head -c 200
curl -s localhost:8000/api/estimates | head -c 200
kill %1
```
Expected: sync returns `estimate_id`/`version_number`; list shows one calculated estimate.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes.py
git commit -m "refactor(api): drop superseded estimate detail route; v0.2 backend foundation complete"
```

---

## Self-Review notes (author)

- **Spec coverage:** §4 data model → Tasks 1–2; §5 integrity/recompute → Task 3; §8 versioning helpers/concurrency retry → Task 4; §7 prompt store (model+seed+read-through) → Tasks 2,5; §8 API (estimates CRUD, calc, versions, rollback, manual-edit) → Tasks 6–8; backward-compat sync/async + keep `build_estimate` → Tasks 3,6. **Deferred to later plans:** chat endpoint + `editor.py` (Plan 2), settings effective-config + provider/test/catalog + prompt edit/reset endpoints (Plan 3), frontend (Plan 4). AppSetting table is created here (Task 2) but consumed in Plan 3.
- **Type consistency:** `create_version(db, estimate, inp, result, *, source, summary)` used identically in Tasks 4/6/8; `recompute_estimate(prev, lines, inp)` identical in Tasks 3/8; `EstimateCard` fields match `_card()`; version field is `version_number` everywhere.
- **No placeholders:** every code step shows real code; commands include expected output.
```
