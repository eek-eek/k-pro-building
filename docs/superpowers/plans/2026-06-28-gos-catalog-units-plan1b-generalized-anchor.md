# Госкаталог цен РК — План 1B: укрупнённый показатель РК + якорь-сверка

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить официальный укрупнённый показатель стоимости РК (НДЦС/УСН РК) как ориентир-сверку к ресурсной смете: новая таблица показателей, провенанс, расчёт укрупнённой оценки и отклонения ресурсной сметы от неё, отображение на фронте. Ресурсные итоги не меняются (якорь — аддитивная информация).

**Architecture:** Новая таблица `generalized_indicators` (₸ за м² общей площади, по типу объекта/региону, с источником и флагом «предварительно»). Идемпотентный сид **предварительных** значений (помечены `needs_review`, подлежат замене официальными — через пайплайн импорта, отдельный План 1C). `compute_cost_anchor` резолвит показатель, считает укрупнённую оценку (площадь × показатель) и отклонение ресурсного `grand_total`. `build_estimate` прикрепляет `cost_anchor` к результату и добавляет предупреждение при отклонении >25%. `recompute_estimate` (ручные правки) обновляет отклонение от нового итога. Фронт показывает якорь в карточке «Итоги».

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (SQLite), Pydantic v2, pytest; ванильный фронт `frontend/app.js`. Опирается на 1A (паттерны моделей/сидов, провенанс).

**Scope:** Только укрупнённый показатель + якорь-сверка. НЕ входит: пайплайн импорта `app/gosdata/` (План 1C — наполнение показателей/каталога из файлов), отдельный «только укрупнённый» режим расчёта, сведение `pricesource` к одному источнику. Спека: `docs/superpowers/specs/2026-06-28-gos-catalog-units-design.md`.

> **Честность данных:** засеянные значения показателей — ПРЕДВАРИТЕЛЬНЫЕ ориентиры (`needs_review=True`), официальные таблицы НДЦС/УСН РК закрыты пейволом и будут загружены позже (План 1C). Во всех местах (нота, предупреждение, фронт) явно писать «предварительный показатель».

---

### Task 1: Таблица `generalized_indicators` + предварительный сид

**Files:**
- Modify: `backend/app/models.py` (модель `GeneralizedIndicator` в конец файла)
- Create: `backend/app/calc/generalized.py` (константы + `seed_generalized_indicators`)
- Modify: `backend/app/seed.py` (вызвать сид в `run_seed`)
- Test: `backend/tests/test_generalized.py`

- [ ] **Step 1: Написать падающий тест сида показателей**

Create `backend/tests/test_generalized.py`:
```python
"""Укрупнённые показатели РК: сид (предварительный) + резолв + якорь-сверка."""
from __future__ import annotations

from app.calc.generalized import (
    GENERALIZED_PRICE_LEVEL, seed_generalized_indicators,
)
from app.models import GeneralizedIndicator


def test_generalized_seeded(db):
    rows = db.query(GeneralizedIndicator).filter_by(price_level=GENERALIZED_PRICE_LEVEL).count()
    assert rows >= 3  # как минимум жилой дом / офис / склад


def test_generalized_seed_idempotent(db):
    before = db.query(GeneralizedIndicator).count()
    seed_generalized_indicators(db)
    after = db.query(GeneralizedIndicator).count()
    assert after == before  # повтор не плодит строк


def test_generalized_values_are_provisional(db):
    # Все засеянные показатели помечены как предварительные (нужен офиц. сборник).
    row = db.query(GeneralizedIndicator).filter_by(object_type="Жилой дом").first()
    assert row is not None
    assert row.needs_review is True
    assert row.value > 0
    assert row.unit == "м²"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && .venv/bin/python -m pytest tests/test_generalized.py -q`
Expected: FAIL (`ImportError` / нет `GeneralizedIndicator`).

- [ ] **Step 3: Добавить модель `GeneralizedIndicator` в конец `models.py`**

```python
class GeneralizedIndicator(Base):
    """Укрупнённый показатель стоимости строительства РК (НДЦС/УСН РК), ₸ за единицу.

    Ориентир/сверка к ресурсной смете. Значения из официальных сборников РК;
    до подтверждения помечаются needs_review (предварительные)."""

    __tablename__ = "generalized_indicators"
    __table_args__ = (
        UniqueConstraint("object_type", "region", "price_level",
                         name="uq_generalized_indicator"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    region: Mapped[str] = mapped_column(String(64), default="KZ")
    value: Mapped[float] = mapped_column(Float)  # ₸ за единицу (обычно м² общей площади)
    unit: Mapped[str] = mapped_column(String(16), default="м²")
    price_level: Mapped[str] = mapped_column(String(48), default="")
    source_code: Mapped[str] = mapped_column(String(64), default="")  # напр. НДЦС РК 8.02-01
    source_url: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
```

- [ ] **Step 4: Создать `backend/app/calc/generalized.py` (константы + сид)**

```python
"""Укрупнённые показатели стоимости РК (НДЦС/УСН РК): сид, резолв, якорь-сверка.

ВНИМАНИЕ: засеянные значения — ПРЕДВАРИТЕЛЬНЫЕ ориентиры (needs_review=True),
подлежат замене значениями из официального сборника РК (пайплайн импорта, План 1C).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GeneralizedIndicator
from ..schemas import BuildingInput, CostAnchor

GENERALIZED_PRICE_LEVEL = "НДЦС-2025-предварительно"

# Предварительные укрупнённые показатели (₸/м² общей площади), национально (KZ).
# ЗАГЛУШКА: заменить официальными значениями НДЦС/УСН РК (План 1C).
_SEED: list[dict] = [
    {"object_type": "Жилой дом", "value": 320000.0},
    {"object_type": "Офис", "value": 360000.0},
    {"object_type": "Коммерческое помещение", "value": 340000.0},
    {"object_type": "Склад", "value": 180000.0},
    {"object_type": "Производственный объект", "value": 260000.0},
]
_SEED_NOTE = "Предварительный ориентир — заменить значением из официального сборника НДЦС/УСН РК"
_SEED_SOURCE = "НДЦС РК 8.02-01 (предв.)"


def seed_generalized_indicators(db: Session, region: str = "KZ") -> None:
    """Идемпотентно засеять предварительные укрупнённые показатели."""
    for row in _SEED:
        exists = db.scalar(
            select(GeneralizedIndicator).where(
                GeneralizedIndicator.object_type == row["object_type"],
                GeneralizedIndicator.region == region,
                GeneralizedIndicator.price_level == GENERALIZED_PRICE_LEVEL,
            )
        )
        if exists:
            continue
        db.add(GeneralizedIndicator(
            object_type=row["object_type"], region=region, value=row["value"],
            unit="м²", price_level=GENERALIZED_PRICE_LEVEL,
            source_code=_SEED_SOURCE, note=_SEED_NOTE, needs_review=True,
        ))
    db.commit()
```
(Импорт `CostAnchor`/`BuildingInput`/`Optional` понадобится в Task 2 — оставить их в импортах сейчас не обязательно; добавить в Task 2. Чтобы файл импортировался в Task 1, ВРЕМЕННО можно не импортировать `CostAnchor`/`BuildingInput`. Простой путь: в Task 1 импортировать только `GeneralizedIndicator`, а `from ..schemas import BuildingInput, CostAnchor` и `from typing import Optional` добавить в Task 2 вместе с функциями, которые их используют.)

> Чтобы не создавать «мёртвый» импорт `CostAnchor` (его ещё нет до Task 2), в Task 1 шапку `generalized.py` оставь БЕЗ строки `from ..schemas import ...` и без `from typing import Optional`. Добавишь их в Task 2.

- [ ] **Step 5: Засеять в `run_seed`**

В `backend/app/seed.py` добавить рядом с другими `from .calc...`:
```python
from .calc.generalized import seed_generalized_indicators
```
И в `run_seed`, после `seed_work_resources(db)`:
```python
        seed_work_resources(db)
        seed_generalized_indicators(db)
```

- [ ] **Step 6: Запустить тест — должен пройти**

Run: `cd backend && .venv/bin/python -m pytest tests/test_generalized.py -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Прогнать весь сьют (нет регрессии)**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: всё зелёное (было 129, стало ~132).

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/app/calc/generalized.py backend/app/seed.py backend/tests/test_generalized.py
git commit -m "feat: таблица укрупнённых показателей РК + предварительный сид (needs_review)"
```

---

### Task 2: Схема `CostAnchor` + резолв показателя + расчёт якоря

**Files:**
- Modify: `backend/app/schemas.py` (класс `CostAnchor` перед `class EstimateResult`; поле `cost_anchor` в `EstimateResult`)
- Modify: `backend/app/calc/generalized.py` (импорты + `resolve_generalized_indicator` + `compute_cost_anchor`)
- Test: `backend/tests/test_generalized.py` (дополнить)

- [ ] **Step 1: Написать падающий тест расчёта якоря**

Добавить в `backend/tests/test_generalized.py`:
```python
def test_resolve_indicator_for_object(db):
    from app.calc.generalized import resolve_generalized_indicator
    from app.schemas import BuildingInput
    ind = resolve_generalized_indicator(db, BuildingInput(object_type="Жилой дом"))
    assert ind is not None and ind.object_type == "Жилой дом"
    none = resolve_generalized_indicator(db, BuildingInput(object_type="НесуществующийТип"))
    assert none is None


def test_compute_cost_anchor(db):
    from app.calc.generalized import compute_cost_anchor
    from app.schemas import BuildingInput
    inp = BuildingInput(object_type="Жилой дом", total_area=1000.0)  # 1000 м²
    anchor = compute_cost_anchor(db, inp, resource_grand=300_000_000.0)
    assert anchor is not None
    assert anchor.indicator_per_unit > 0
    assert anchor.value == round(1000.0 * anchor.indicator_per_unit)  # площадь × показатель
    assert anchor.provisional is True
    # отклонение ресурсной (300M) от укрупнённой (1000×320000=320M) ≈ -6.25%
    assert anchor.deviation_pct == round((300_000_000 - anchor.value) / anchor.value * 100, 1)


def test_compute_cost_anchor_none_when_no_indicator(db):
    from app.calc.generalized import compute_cost_anchor
    from app.schemas import BuildingInput
    anchor = compute_cost_anchor(db, BuildingInput(object_type="НетТакого"), 1.0)
    assert anchor is None
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && .venv/bin/python -m pytest tests/test_generalized.py -q`
Expected: FAIL (нет `CostAnchor` / `resolve_generalized_indicator` / `compute_cost_anchor`).

- [ ] **Step 3: Добавить схему `CostAnchor` в `schemas.py`**

В `backend/app/schemas.py` ПЕРЕД `class EstimateResult(BaseModel):` добавить:
```python
class CostAnchor(BaseModel):
    """Укрупнённый ориентир стоимости РК (НДЦС/УСН) для сверки с ресурсной сметой."""

    value: float                # ₸, укрупнённая оценка = площадь × показатель
    indicator_per_unit: float   # ₸ за единицу (обычно м²)
    unit: str = "м²"
    area: float = 0.0
    source_code: str = ""
    source_url: str = ""
    note: str = ""
    provisional: bool = True     # значение предварительное (нужен официальный сборник)
    resource_grand: float = 0.0  # grand_total ресурсной сметы (для сравнения)
    deviation_pct: float = 0.0   # отклонение ресурсной от укрупнённой, %
```
И в `class EstimateResult(BaseModel):` добавить поле (например, после `totals: EstimateTotals = ...`):
```python
    cost_anchor: Optional["CostAnchor"] = None
```
(`Optional` уже импортирован в schemas.py.)

- [ ] **Step 4: Реализовать резолв + расчёт якоря в `generalized.py`**

В шапке `backend/app/calc/generalized.py` добавить импорты (которые отложили из Task 1):
```python
from typing import Optional
```
и
```python
from ..schemas import BuildingInput, CostAnchor
```
В конец `generalized.py` добавить:
```python
def resolve_generalized_indicator(
    db: Session, inp: BuildingInput
) -> Optional[GeneralizedIndicator]:
    """Найти укрупнённый показатель под объект: регион города → KZ."""
    region = inp.city.split("/")[0].strip() or "KZ"
    for reg in (region, "KZ"):
        row = db.scalar(
            select(GeneralizedIndicator).where(
                GeneralizedIndicator.object_type == inp.object_type,
                GeneralizedIndicator.region == reg,
            )
        )
        if row is not None:
            return row
    return None


def compute_cost_anchor(
    db: Session, inp: BuildingInput, resource_grand: float
) -> Optional[CostAnchor]:
    """Укрупнённый ориентир + отклонение ресурсной сметы (None, если показателя нет)."""
    ind = resolve_generalized_indicator(db, inp)
    if ind is None:
        return None
    area = inp.total_area or 0.0
    value = round(area * ind.value)
    deviation = round((resource_grand - value) / value * 100, 1) if value else 0.0
    return CostAnchor(
        value=value, indicator_per_unit=ind.value, unit=ind.unit, area=area,
        source_code=ind.source_code, source_url=ind.source_url, note=ind.note,
        provisional=ind.needs_review, resource_grand=round(resource_grand),
        deviation_pct=deviation,
    )
```

- [ ] **Step 5: Запустить тесты — должны пройти**

Run: `cd backend && .venv/bin/python -m pytest tests/test_generalized.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/calc/generalized.py backend/tests/test_generalized.py
git commit -m "feat: CostAnchor + резолв укрупнённого показателя + расчёт укрупнённой оценки/отклонения"
```

---

### Task 3: Интеграция якоря в `build_estimate` и `recompute_estimate`

**Files:**
- Modify: `backend/app/calc/estimate.py` (импорт + прикрепить `cost_anchor` + предупреждение; обновить в `recompute_estimate`)
- Test: `backend/tests/test_db_catalog.py` (дополнить) или `backend/tests/test_generalized.py`

- [ ] **Step 1: Написать падающий тест интеграции**

Добавить в `backend/tests/test_generalized.py`:
```python
def test_build_estimate_attaches_anchor(db):
    from app.calc import build_estimate
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput
    inp = BuildingInput(demo_mode=True, use_search=False, object_type="Жилой дом")
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    assert r.cost_anchor is not None
    assert r.cost_anchor.value > 0
    assert r.cost_anchor.resource_grand == round(r.totals.grand_total)


def test_anchor_deviation_warning(db):
    """Большое отклонение ресурсной сметы от укрупнённого → предупреждение."""
    from app.calc import build_estimate
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput
    inp = BuildingInput(demo_mode=True, use_search=False, object_type="Жилой дом")
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    if abs(r.cost_anchor.deviation_pct) > 25:
        assert any("укрупнённого ориентира" in w for w in r.warnings)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && .venv/bin/python -m pytest tests/test_generalized.py::test_build_estimate_attaches_anchor -q`
Expected: FAIL (`r.cost_anchor is None`).

- [ ] **Step 3: Прикрепить якорь в `build_estimate`**

В `backend/app/calc/estimate.py` добавить импорт рядом с другими `from .` импортами:
```python
from .generalized import compute_cost_anchor
```
В `build_estimate`, ПЕРЕД `return EstimateResult(...)` (после блока, где сформированы `totals` и `warnings`, `clarifications`) добавить:
```python
    cost_anchor = compute_cost_anchor(db, inp, totals.grand_total)
    if cost_anchor is not None and abs(cost_anchor.deviation_pct) > 25:
        warnings.append(
            f"Ресурсная смета отклоняется от укрупнённого ориентира РК на "
            f"{cost_anchor.deviation_pct:+.0f}% (укрупнённо ≈ {cost_anchor.value:,.0f} ₸"
            + ("; предварительный показатель" if cost_anchor.provisional else "") + ")."
        )
```
И в вызове `return EstimateResult(...)` добавить аргумент:
```python
        cost_anchor=cost_anchor,
```

- [ ] **Step 4: Сохранить якорь при ручном пересчёте `recompute_estimate`**

В `recompute_estimate`, перед `return EstimateResult(...)` (после вычисления `grand`/`totals`) добавить:
```python
    anchor = prev.cost_anchor
    if anchor is not None:
        anchor = anchor.model_copy(update={
            "resource_grand": round(grand),
            "deviation_pct": round((grand - anchor.value) / anchor.value * 100, 1)
                              if anchor.value else 0.0,
        })
```
И в `return EstimateResult(...)` этого метода добавить:
```python
        cost_anchor=anchor,
```

- [ ] **Step 5: Запустить тесты якоря — должны пройти**

Run: `cd backend && .venv/bin/python -m pytest tests/test_generalized.py -q`
Expected: PASS (8 passed).

- [ ] **Step 6: Полный сьют — нет регрессии ресурсных итогов**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: всё зелёное (~134). Якорь аддитивен — прежние тесты итогов/парности не должны измениться. Если упал тест, проверяющий точные итоги — СТОП и сообщить (значит якорь влияет на итоги, чего быть не должно).

- [ ] **Step 7: Commit**

```bash
git add backend/app/calc/estimate.py backend/tests/test_generalized.py
git commit -m "feat: укрупнённый якорь-сверка в build_estimate + сохранение при ручном пересчёте"
```

---

### Task 4: Фронт — укрупнённый якорь в карточке «Итоги»

**Files:**
- Modify: `frontend/app.js` (`renderTotals` принимает якорь; вызов передаёт `r.cost_anchor`)

- [ ] **Step 1: Передать якорь в `renderTotals`**

В `frontend/app.js` найти вызов в `renderResult`:
```javascript
  parts.push(renderTotals(r.totals));
```
заменить на:
```javascript
  parts.push(renderTotals(r.totals, r.cost_anchor));
```

- [ ] **Step 2: Отрисовать блок якоря в `renderTotals`**

Заменить функцию `renderTotals` на версию с якорем:
```javascript
function renderTotals(t, anchor) {
  if (!t) return "";
  const row = (label, val, cls = "") => `<div class="t-row ${cls}"><span>${label}</span><span>${money(val)} ₸</span></div>`;
  let anchorHtml = "";
  if (anchor && anchor.value) {
    const dev = anchor.deviation_pct;
    const devCls = Math.abs(dev) > 25 ? "warn" : "ok";
    const prov = anchor.provisional ? ` <span class="badge">предварительно</span>` : "";
    const src = anchor.source_code ? ` · источник: ${escapeHtml(anchor.source_code)}` : "";
    anchorHtml = `<div class="anchor-box">
      <div class="anchor-head">Укрупнённый ориентир РК${prov}</div>
      <div class="t-row"><span>Укрупнённо (${escapeHtml(anchor.unit)} × показатель)</span><span>${money(anchor.value)} ₸</span></div>
      <div class="t-row ${devCls}"><span>Отклонение ресурсной сметы</span><span>${dev > 0 ? "+" : ""}${dev}%</span></div>
      <div class="hint" style="margin-top:6px">${escapeHtml(anchor.note || "")}${src}</div>
    </div>`;
  }
  return `<div class="card"><h3>Итоги</h3><div class="totals">
    ${row("Прямые затраты", t.direct)}
    ${row(`Накладные (${t.overhead_pct}%)`, t.overhead)}
    ${row(`Резерв (${t.contingency_pct}%)`, t.contingency)}
    ${row(`НДС (${t.vat_pct}%)`, t.vat)}
    ${row("ИТОГО с НДС", t.grand_total, "grand")}
  </div>${anchorHtml}</div>`;
}
```

- [ ] **Step 3: Проверить визуально (smoke)**

Run (демо-сервер):
```bash
cd backend && lsof -ti tcp:8000 | xargs kill -9 2>/dev/null; \
LLM_PROVIDER=demo .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning &
```
Затем создать смету и проверить, что в ответе расчёта есть `cost_anchor`:
```bash
sleep 3
EST=$(curl -s -X POST http://127.0.0.1:8000/api/estimates -H 'Content-Type: application/json' -d '{"name":"anchor-smoke"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
JOB=$(curl -s -X POST http://127.0.0.1:8000/api/estimates/$EST/calc -H 'Content-Type: application/json' -d '{"demo_mode":true,"use_search":false,"object_type":"Жилой дом"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
sleep 2
curl -s http://127.0.0.1:8000/api/estimate/$JOB | python3 -c 'import sys,json;r=json.load(sys.stdin).get("result") or {};a=r.get("cost_anchor");print("cost_anchor:",a is not None, a.get("value") if a else None, a.get("deviation_pct") if a else None)'
lsof -ti tcp:8000 | xargs kill -9 2>/dev/null
```
Expected: `cost_anchor: True <число> <отклонение>`.

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "feat(ui): укрупнённый ориентир РК и отклонение в карточке Итоги"
```

(CSS-классы `.anchor-box`/`.anchor-head`/`.warn`/`.ok` опциональны — без них блок отрисуется без декора. Если хочется — добавить лёгкие стили в `frontend/styles.css`, но это не обязательно для функции.)

---

## Self-Review

**1. Spec coverage (1B scope):**
- Таблица показателей + провенанс + предварительный сид → Task 1 ✓
- Резолв + расчёт укрупнённой оценки/отклонения + схема `CostAnchor` → Task 2 ✓
- Интеграция якоря в расчёт (build + recompute) + предупреждение, без регрессии итогов → Task 3 ✓
- Отображение на фронте → Task 4 ✓
- Отложено (вне 1B): пайплайн импорта `app/gosdata/` (План 1C), «только укрупнённый» режим, сведение pricesource.

**2. Placeholder scan:** код приведён полностью; единственные «заглушки» — это намеренно предварительные ЗНАЧЕНИЯ показателей (помечены needs_review + ноты), что является осознанным дизайн-решением (официальные таблицы закрыты, грузятся в 1C). ✓

**3. Type consistency:** `compute_cost_anchor(db, inp, resource_grand) -> Optional[CostAnchor]`; `CostAnchor` поля совпадают с конструированием в `compute_cost_anchor` и чтением во фронте (`value`, `deviation_pct`, `provisional`, `unit`, `source_code`, `note`); `EstimateResult.cost_anchor: Optional[CostAnchor]`; `recompute_estimate` использует `prev.cost_anchor.model_copy(update=...)`. ✓

**4. Риски/заметки:**
- Якорь аддитивен → ресурсные итоги и тесты парности 1A не меняются (проверяется полным сьютом в Task 3).
- Циклы импорта: `estimate.py` → `from .generalized import compute_cost_anchor`; `generalized.py` → `from ..schemas import ...` и `from ..models import ...`. `schemas`/`models` не импортируют `calc` → цикла нет.
- Порог отклонения 25% — эвристика; вынесена инлайн, при желании позже в конфиг.
- Засеянные значения ПРЕДВАРИТЕЛЬНЫЕ — фронт/предупреждение это явно показывают; настоящие числа придут в 1C.

## Execution Handoff

План сохранён: `docs/superpowers/plans/2026-06-28-gos-catalog-units-plan1b-generalized-anchor.md`.
Следующий после 1B — **План 1C**: пайплайн импорта `app/gosdata/` (parsers/normalize/mapping/load), чтобы заменить предварительные показатели официальными и наполнять каталог из файлов.
