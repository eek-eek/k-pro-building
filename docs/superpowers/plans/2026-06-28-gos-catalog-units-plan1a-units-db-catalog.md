# Госкаталог цен РК — План 1A: реестр единиц + каталог ресурсов в БД

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Навести порядок в единицах ресурсного метода и вынести ресурсный каталог из кода в БД с провенансом — фундамент под наполнение официальными данными РК, без изменения итогов существующих смет.

**Architecture:** Канонический реестр единиц (`app/calc/units.py` + таблица `units`) с валидацией `kind↔единица`. Каталог `COMPOSITIONS` идемпотентно сидируется в новую таблицу `work_resources` с провенансом (источник/уровень цен/регион). `build_estimate` берёт состав работы из БД (`db_snapshot_for`) с фолбэком на встроенный `snapshot_for`. Парность гарантируется тестом: ролл-ап из БД == ролл-ап из кода для каждой работы.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (`Mapped`/`mapped_column`, SQLite), Pydantic v2, pytest. Паттерны из репо: `seed_prices` (идемпотентный сид), `init_db` (`create_all` + guarded ALTER), фикстура `db` поверх `run_seed`.

**Scope:** Только фундамент (единицы + каталог в БД). НЕ входит: укрупнённый режим, пайплайн импорта, фронт-пометки, импорт ЕРЕР — это **План 1B** (отдельно, после 1A). Спека: `docs/superpowers/specs/2026-06-28-gos-catalog-units-design.md`.

---

### Task 1: Реестр канонических единиц + валидация

**Files:**
- Create: `backend/app/calc/units.py`
- Modify: `backend/app/models.py` (добавить модель `Unit` в конец файла)
- Modify: `backend/app/seed.py` (вызвать `seed_units` в `run_seed`)
- Test: `backend/tests/test_units.py`

- [ ] **Step 1: Написать падающий тест валидатора единиц**

Create `backend/tests/test_units.py`:
```python
"""Реестр единиц: валидация соответствия вид ресурса ↔ единица."""
from __future__ import annotations

from app.calc.units import unit_known, unit_ok_for_kind


def test_known_units():
    assert unit_known("чел-ч")
    assert unit_known("маш-ч")
    assert unit_known("м³")
    assert not unit_known("попугай")


def test_unit_matches_kind():
    assert unit_ok_for_kind("чел-ч", "labor")
    assert unit_ok_for_kind("маш-ч", "machine")
    assert unit_ok_for_kind("м³", "material")
    assert unit_ok_for_kind("компл", "material")


def test_unit_mismatch_kind_rejected():
    assert not unit_ok_for_kind("чел-ч", "material")   # время — не материал
    assert not unit_ok_for_kind("м³", "labor")         # объём — не труд
    assert not unit_ok_for_kind("маш-ч", "labor")      # машино-час — не труд
    assert not unit_ok_for_kind("попугай", "material")  # неизвестная единица
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd backend && .venv/bin/python -m pytest tests/test_units.py -q`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.calc.units'`

- [ ] **Step 3: Реализовать реестр единиц**

Create `backend/app/calc/units.py`:
```python
"""Реестр канонических единиц измерения ресурсного метода + валидация kind↔единица.

Единый источник правды по единицам. Строки совпадают с используемыми в
COMPOSITIONS, чтобы сид каталога не требовал переименования значений.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Unit

# Каноническая единица → размерность.
UNIT_DIMENSION: dict[str, str] = {
    "чел-ч": "labor_time",
    "маш-ч": "machine_time",
    "маш-см": "machine_time",
    "м³": "volume",
    "л": "volume",
    "м²": "area",
    "м": "length",
    "км": "length",
    "т": "mass",
    "кг": "mass",
    "шт": "count",
    "компл": "set",
}

# Допустимые размерности для вида ресурса.
KIND_DIMENSIONS: dict[str, set[str]] = {
    "labor": {"labor_time"},
    "machine": {"machine_time"},
    "material": {"mass", "volume", "area", "count", "length", "set"},
}

# Человекочитаемые ярлыки (для реестра/UI).
UNIT_TITLE: dict[str, str] = {
    "чел-ч": "человеко-час", "маш-ч": "машино-час", "маш-см": "машино-смена",
    "м³": "кубический метр", "м²": "квадратный метр", "м": "метр", "км": "километр",
    "т": "тонна", "кг": "килограмм", "шт": "штука", "компл": "комплект", "л": "литр",
}


def unit_known(unit: str) -> bool:
    return unit in UNIT_DIMENSION


def unit_ok_for_kind(unit: str, kind: str) -> bool:
    """True, если единица существует и её размерность допустима для вида ресурса."""
    dim = UNIT_DIMENSION.get(unit)
    if dim is None:
        return False
    return dim in KIND_DIMENSIONS.get(kind, set())


def seed_units(db: Session) -> None:
    """Идемпотентно засеять реестр единиц в БД."""
    for code, dim in UNIT_DIMENSION.items():
        if db.get(Unit, code) is None:
            db.add(Unit(code=code, title=UNIT_TITLE.get(code, code), dimension=dim))
    db.commit()
```

- [ ] **Step 4: Добавить модель `Unit` в `models.py`**

В конец `backend/app/models.py` добавить:
```python
class Unit(Base):
    """Реестр канонических единиц измерения (см. app/calc/units.py)."""

    __tablename__ = "units"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(64), default="")
    dimension: Mapped[str] = mapped_column(String(16))  # labor_time|machine_time|mass|volume|area|count|length|set
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
```

- [ ] **Step 5: Запустить тест валидатора — должен пройти**

Run: `cd backend && .venv/bin/python -m pytest tests/test_units.py -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Засеять единицы в `run_seed`**

В `backend/app/seed.py` импорт и вызов. Заменить:
```python
from .calc.pricing import seed_prices
```
на:
```python
from .calc.pricing import seed_prices
from .calc.units import seed_units
```
И в теле `run_seed`, после `seed_prices(db)`:
```python
        seed_prices(db)
        seed_units(db)
        seed_prompts(db)
```

- [ ] **Step 7: Тест сида единиц (идемпотентность)**

Добавить в `backend/tests/test_units.py`:
```python
def test_seed_units_idempotent(db):
    from app.calc.units import seed_units, UNIT_DIMENSION
    from app.models import Unit
    seed_units(db)
    seed_units(db)  # повтор не должен падать/дублировать (PK)
    assert db.query(Unit).count() == len(UNIT_DIMENSION)
    row = db.get(Unit, "чел-ч")
    assert row is not None and row.dimension == "labor_time"
```

Run: `cd backend && .venv/bin/python -m pytest tests/test_units.py -q`
Expected: PASS (4 passed)

- [ ] **Step 8: Commit**

```bash
git add backend/app/calc/units.py backend/app/models.py backend/app/seed.py backend/tests/test_units.py
git commit -m "feat: реестр канонических единиц + валидация kind↔единица"
```

---

### Task 2: Таблица `work_resources` + идемпотентный сид из COMPOSITIONS

**Files:**
- Modify: `backend/app/models.py` (модель `WorkResource` в конец файла)
- Modify: `backend/app/calc/resource_catalog.py` (импорты + `SEED_PRICE_LEVEL` + `seed_work_resources`)
- Modify: `backend/app/seed.py` (вызвать `seed_work_resources` в `run_seed`)
- Test: `backend/tests/test_work_resources.py`

- [ ] **Step 1: Написать падающий тест сида каталога**

Create `backend/tests/test_work_resources.py`:
```python
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
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && .venv/bin/python -m pytest tests/test_work_resources.py -q`
Expected: FAIL с `ImportError: cannot import name 'SEED_PRICE_LEVEL'` / `WorkResource`.

- [ ] **Step 3: Добавить модель `WorkResource` в `models.py`**

В конец `backend/app/models.py` добавить:
```python
class WorkResource(Base):
    """Ресурсный состав работы (вынос COMPOSITIONS в БД, с провенансом)."""

    __tablename__ = "work_resources"
    __table_args__ = (
        UniqueConstraint("work_key", "code", "region", "price_level",
                         name="uq_work_resource"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_key: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(64))
    official_code: Mapped[str] = mapped_column(String(64), default="")  # код ЕРЕР/ССЦ (Phase 2)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))  # material|labor|machine
    unit: Mapped[str] = mapped_column(String(16))
    consumption: Mapped[float] = mapped_column(Float)
    rank: Mapped[str] = mapped_column(String(16), default="")  # разряд (для labor)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16), default="seed")  # seed|ndcs|erer|ssc|manual
    price_level: Mapped[str] = mapped_column(String(48), default="")
    region: Mapped[str] = mapped_column(String(64), default="KZ")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
```

- [ ] **Step 4: Добавить импорты + сид в `resource_catalog.py`**

В шапке `backend/app/calc/resource_catalog.py` после `from dataclasses import dataclass` добавить:
```python
from sqlalchemy import select
from sqlalchemy.orm import Session
```
В конец `backend/app/calc/resource_catalog.py` добавить:
```python
SEED_PRICE_LEVEL = "рынок-Астана-2026"


def seed_work_resources(db: Session, region: str = "KZ") -> None:
    """Идемпотентно засеять ресурсный каталог из COMPOSITIONS в БД с провенансом.

    needs_review выставляется, если единица не проходит валидацию kind↔единица —
    чтобы навести порядок в человеко-часах/машино-часах/материалах.
    """
    from ..models import WorkResource
    from .units import unit_ok_for_kind

    for work_key, specs in COMPOSITIONS.items():
        for s in specs:
            exists = db.scalar(
                select(WorkResource).where(
                    WorkResource.work_key == work_key,
                    WorkResource.code == s.code,
                    WorkResource.region == region,
                    WorkResource.price_level == SEED_PRICE_LEVEL,
                )
            )
            if exists:
                continue
            db.add(WorkResource(
                work_key=work_key, code=s.code, name=s.name, kind=s.kind,
                unit=s.unit, consumption=s.consumption, price=s.price,
                source="seed", price_level=SEED_PRICE_LEVEL, region=region,
                needs_review=not unit_ok_for_kind(s.unit, s.kind),
            ))
    db.commit()
```

- [ ] **Step 5: Засеять каталог в `run_seed`**

В `backend/app/seed.py` заменить:
```python
from .calc.units import seed_units
```
на:
```python
from .calc.units import seed_units
from .calc.resource_catalog import seed_work_resources
```
И в теле `run_seed`, после `seed_units(db)`:
```python
        seed_units(db)
        seed_work_resources(db)
```

- [ ] **Step 6: Запустить тест — должен пройти**

Run: `cd backend && .venv/bin/python -m pytest tests/test_work_resources.py -q`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/calc/resource_catalog.py backend/app/seed.py backend/tests/test_work_resources.py
git commit -m "feat: ресурсный каталог в БД (work_resources) + идемпотентный сид из COMPOSITIONS"
```

---

### Task 3: Ролл-ап из БД в `build_estimate` + парность/регресс

**Files:**
- Modify: `backend/app/calc/resource_catalog.py` (`db_snapshot_for`)
- Modify: `backend/app/calc/estimate.py` (использовать `db_snapshot_for`)
- Test: `backend/tests/test_db_catalog.py`

- [ ] **Step 1: Написать падающий тест парности (ролл-ап из БД == из кода)**

Create `backend/tests/test_db_catalog.py`:
```python
"""Каталог из БД даёт те же удельные цены, что встроенный COMPOSITIONS (нет регрессии)."""
from __future__ import annotations

from app.calc.resource_catalog import (
    COMPOSITIONS, db_snapshot_for, rollup, snapshot_for,
)


def test_db_snapshot_parity_per_work(db):
    """Для каждой работы ролл-ап из БД совпадает с ролл-апом из кода."""
    for key in COMPOSITIONS:
        assert rollup(db_snapshot_for(db, key)) == rollup(snapshot_for(key)), key


def test_db_snapshot_fallback_when_absent(db):
    """Нет данных для ключа → фолбэк на встроенный состав (или пусто)."""
    assert db_snapshot_for(db, "no_such_work") == snapshot_for("no_such_work")  # == []
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db_catalog.py -q`
Expected: FAIL с `ImportError: cannot import name 'db_snapshot_for'`.

- [ ] **Step 3: Реализовать `db_snapshot_for`**

В конец `backend/app/calc/resource_catalog.py` добавить:
```python
def db_snapshot_for(
    db: Session, work_key: str, region: str = "KZ",
    price_level: str = SEED_PRICE_LEVEL,
) -> list[ResourceLine]:
    """Снимок ресурсов работы из БД (резолв region → KZ, фолбэк на COMPOSITIONS).

    Порядок строк — по id (= порядок сида = порядок COMPOSITIONS), чтобы индексы
    ресурсов в строке сметы были стабильны для ручной правки.
    """
    from ..models import WorkResource

    for reg in (region, "KZ"):
        rows = db.scalars(
            select(WorkResource)
            .where(
                WorkResource.work_key == work_key,
                WorkResource.region == reg,
                WorkResource.price_level == price_level,
            )
            .order_by(WorkResource.id)
        ).all()
        if rows:
            return [
                ResourceLine(code=r.code, name=r.name, kind=r.kind, unit=r.unit,
                             consumption=r.consumption, price=r.price)
                for r in rows
            ]
    return snapshot_for(work_key)
```

- [ ] **Step 4: Запустить тест парности — должен пройти**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db_catalog.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Переключить `build_estimate` на каталог из БД**

В `backend/app/calc/estimate.py` в `build_estimate`, в импорте сверху добавить `db_snapshot_for` к существующему импорту из resource_catalog. Найти строку:
```python
from .resource_catalog import rollup, snapshot_for
```
заменить на:
```python
from .resource_catalog import db_snapshot_for, rollup, snapshot_for
```
Затем в теле цикла заменить:
```python
            resources = snapshot_for(key)
```
на:
```python
            resources = db_snapshot_for(db, key, region)
```
(`db` и `region` уже в области видимости `build_estimate`.)

- [ ] **Step 6: Тест отсутствия регрессии итогов (end-to-end)**

Добавить в `backend/tests/test_db_catalog.py`:
```python
def test_build_estimate_uses_db_no_regression(db):
    """build_estimate на каталоге из БД даёт ту же удельную цену каркаса, что из кода."""
    from app.calc import build_estimate
    from app.norms import resolve_norm_profile
    from app.schemas import BuildingInput

    inp = BuildingInput(demo_mode=True, use_search=False)
    profile = resolve_norm_profile(db, inp)
    r = build_estimate(db, inp, profile)
    frame = next(ln for ln in r.lines if ln.title == "Бетон монолитного каркаса")
    # удельная цена = материал+труд+машины из каталога (БД) = как в COMPOSITIONS
    mat, lab, mach = rollup(snapshot_for("frame_concrete"))
    unit_cost = mat + lab + mach
    assert frame.material_price + frame.labor_price + frame.machine_price == unit_cost
    assert frame.total == round(frame.quantity * unit_cost)
```

Run: `cd backend && .venv/bin/python -m pytest tests/test_db_catalog.py -q`
Expected: PASS (3 passed)

- [ ] **Step 7: Прогнать весь бэкенд-сьют (нет регрессии)**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: PASS — все прежние тесты зелёные + новые (units 4, work_resources 3, db_catalog 3). Ожидаемо ~129 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/calc/resource_catalog.py backend/app/calc/estimate.py backend/tests/test_db_catalog.py
git commit -m "feat: build_estimate берёт ресурсный состав из БД (db_snapshot_for) с парностью и фолбэком"
```

---

## Self-Review

**1. Spec coverage (Phase 1A scope):**
- Реестр канонических единиц + валидация → Task 1 ✓
- Каталог ресурсов в БД + провенанс (source/price_level/region/rank/official_code) → Task 2 ✓
- Ролл-ап из БД в расчёт + парность/нет регрессии → Task 3 ✓
- Отложено в План 1B (вне 1A): укрупнённый режим, `generalized_indicator`, пайплайн `app/gosdata/`, фронт-пометки, импорт ЕРЕР. Зафиксировано в Scope.

**2. Placeholder scan:** код приведён полностью в каждом шаге; команд/ожиданий нет «TBD». ✓

**3. Type consistency:** `db_snapshot_for(db, work_key, region, price_level)` и `seed_work_resources(db, region)` используют один `SEED_PRICE_LEVEL`; `unit_ok_for_kind(unit, kind)` зовётся в сиде; модель `WorkResource` поля совпадают с тем, что пишет сид и читает `db_snapshot_for`. `Unit.code` PK строковый — `db.get(Unit, code)` корректно. ✓

**4. Риски/заметки:**
- «компл» принят как каноничная единица размерности `set` (комплект) — это легитимно; декомпозиция blended-комплектов (фасад/ОВиК/электрика) на реальные материалы отложена до наполнения официальными данными (1B/2).
- Сид region="KZ"; `build_estimate` резолвит регион города → KZ (фолбэк), поэтому каталог из БД реально используется, а итоги не меняются (парность доказана по каждому ключу).
- Новые таблицы подхватываются `create_all` в `init_db` (модели в `models.py`); guarded ALTER не нужен (таблицы новые, не колонки в старых).

## Execution Handoff

План сохранён: `docs/superpowers/plans/2026-06-28-gos-catalog-units-plan1a-units-db-catalog.md`.
После реализации 1A — отдельный **План 1B** (укрупнённый режим НДЦС/УСН РК + пайплайн импорта `app/gosdata/` + фронт-пометки источника).
