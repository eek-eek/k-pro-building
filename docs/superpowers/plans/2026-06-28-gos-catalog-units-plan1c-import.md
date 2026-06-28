# Госкаталог цен РК — План 1C: пайплайн импорта `app/gosdata/`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Наполнять каталог официальными данными РК из файлов: CSV-импорт укрупнённых показателей (`generalized_indicators`) и ресурсного состава (`work_resources`) с валидацией единиц/видов, провенансом, идемпотентным upsert и карантином битых строк. Заменяет предварительные плейсхолдеры 1A/1B реальными значениями, когда оператор их получит.

**Architecture:** Source-agnostic: вход — **CSV** (оператор заполняет из легально полученного источника: выгрузка сметной программы / открытые НПА). Пакет `app/gosdata/`: `report.py` (отчёт), `core.py` (валидация + upsert + run-функции), `__main__.py` (CLI). Парсинг через stdlib `csv` (без новых зависимостей). Никаких сетевых обращений/скрейпинга.

**Tech Stack:** Python 3.11 stdlib `csv`/`io`, SQLAlchemy 2.0, Pydantic v2, pytest. Опирается на 1A (units-реестр, `WorkResource`) и 1B (`GeneralizedIndicator`).

**Scope:** CSV-импорт двух таблиц + CLI + шаблоны. НЕ входит: парсинг PDF/Excel напрямую (оператор экспортирует в CSV), сетевой fetch, авто-нормировка единиц к канонической (валидируем, не конвертируем). Спека: `docs/superpowers/specs/2026-06-28-gos-catalog-units-design.md` §4.

> **Честность:** импортированные строки получают провенанс из файла (`source_code`/`source_url`) и `needs_review` из колонки (по умолчанию `false` — официальные данные подтверждены оператором). Импорт НЕ выдаёт предварительные значения за официальные — источник всегда в провенансе.

---

### Task 1: Каркас `app/gosdata/` + импорт укрупнённых показателей

**Files:**
- Create: `backend/app/gosdata/__init__.py`
- Create: `backend/app/gosdata/report.py`
- Create: `backend/app/gosdata/core.py`
- Test: `backend/tests/test_gosdata.py`

- [ ] **Step 1: Падающий тест импорта укрупнённых из CSV**

Create `backend/tests/test_gosdata.py`:
```python
"""Импорт официальных данных РК из CSV (app/gosdata)."""
from __future__ import annotations

from app.gosdata.core import run_import_generalized
from app.models import GeneralizedIndicator

_CSV = """object_type,region,value,unit,price_level,source_code,needs_review
Жилой дом,Астана,310000,м²,ССЦ-2026,НДЦС РК 8.02-01-2025,false
Офис,Астана,355000,м²,ССЦ-2026,НДЦС РК 8.02-01-2025,false
"""


def test_import_generalized_inserts(db):
    report = run_import_generalized(db, _CSV)
    assert report.inserted == 2 and report.skipped == 0 and not report.errors
    row = db.query(GeneralizedIndicator).filter_by(
        object_type="Жилой дом", region="Астана", price_level="ССЦ-2026").first()
    assert row is not None
    assert row.value == 310000
    assert row.source_code == "НДЦС РК 8.02-01-2025"
    assert row.needs_review is False  # официальные данные из файла


def test_import_generalized_idempotent_upsert(db):
    run_import_generalized(db, _CSV)
    r2 = run_import_generalized(db, _CSV.replace("310000", "315000"))
    assert r2.updated == 2 and r2.inserted == 0  # те же ключи → обновление
    row = db.query(GeneralizedIndicator).filter_by(
        object_type="Жилой дом", region="Астана", price_level="ССЦ-2026").first()
    assert row.value == 315000


def test_import_generalized_quarantines_bad_rows(db):
    bad = """object_type,region,value,unit,price_level
,Астана,1,м²,X
Жилой дом,Астана,-5,м²,X
Жилой дом,Астана,100,попугай,X
"""
    report = run_import_generalized(db, bad)
    assert report.inserted == 0 and report.skipped == 3
    assert len(report.errors) == 3  # нет object_type / value<0 / неизвестная единица
```

- [ ] **Step 2: Запустить — упадёт**

Run: `cd backend && .venv/bin/python -m pytest tests/test_gosdata.py -q`
Expected: FAIL (`ModuleNotFoundError: app.gosdata`).

- [ ] **Step 3: `report.py`**

Create `backend/app/gosdata/__init__.py`:
```python
"""Импорт официальных данных РК (укрупнённые показатели, ресурсный каталог) из CSV."""
```
Create `backend/app/gosdata/report.py`:
```python
"""Отчёт об импорте."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportReport:
    target: str
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.target}: +{self.inserted} новых, ~{self.updated} обновлено, "
                f"{self.skipped} пропущено, ошибок {len(self.errors)}")
```

- [ ] **Step 4: `core.py` — валидация + upsert + run_import_generalized**

Create `backend/app/gosdata/core.py`:
```python
"""Валидация строк, upsert в БД и оркестрация импорта из CSV."""
from __future__ import annotations

import csv
import io
import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calc.units import unit_known
from ..models import GeneralizedIndicator
from .report import ImportReport


def _to_float(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _to_bool(value, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "да", "y"}


def _validate_generalized(row: dict) -> tuple[Optional[dict], Optional[str]]:
    object_type = (row.get("object_type") or "").strip()
    if not object_type:
        return None, "нет object_type"
    value = _to_float(row.get("value"))
    if value is None or value <= 0:
        return None, f"некорректное value: {row.get('value')!r}"
    unit = (row.get("unit") or "м²").strip()
    if not unit_known(unit):
        return None, f"неизвестная единица: {unit!r}"
    return {
        "object_type": object_type,
        "region": (row.get("region") or "KZ").strip(),
        "value": value,
        "unit": unit,
        "price_level": (row.get("price_level") or "import").strip(),
        "source_code": (row.get("source_code") or "").strip(),
        "source_url": (row.get("source_url") or "").strip(),
        "note": (row.get("note") or "").strip(),
        "needs_review": _to_bool(row.get("needs_review"), default=False),
    }, None


def _upsert_generalized(db: Session, c: dict) -> str:
    existing = db.scalar(
        select(GeneralizedIndicator).where(
            GeneralizedIndicator.object_type == c["object_type"],
            GeneralizedIndicator.region == c["region"],
            GeneralizedIndicator.price_level == c["price_level"],
        )
    )
    if existing is None:
        db.add(GeneralizedIndicator(**c))
        return "inserted"
    for k, v in c.items():
        setattr(existing, k, v)
    return "updated"


def run_import_generalized(db: Session, csv_text: str) -> ImportReport:
    report = ImportReport(target="generalized_indicators")
    reader = csv.DictReader(io.StringIO(csv_text))
    for i, row in enumerate(reader, start=2):  # 1 — заголовок
        clean, err = _validate_generalized(row)
        if err:
            report.skipped += 1
            report.errors.append(f"строка {i}: {err}")
            continue
        result = _upsert_generalized(db, clean)
        setattr(report, result, getattr(report, result) + 1)
    db.commit()
    return report
```

- [ ] **Step 5: Запустить тест — должен пройти**

Run: `cd backend && .venv/bin/python -m pytest tests/test_gosdata.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Полный сьют (нет регрессии)**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: всё зелёное (167 → 170).

- [ ] **Step 7: Commit**

```bash
git add backend/app/gosdata/__init__.py backend/app/gosdata/report.py backend/app/gosdata/core.py backend/tests/test_gosdata.py
git commit -m "feat(1c): пайплайн импорта app/gosdata — CSV укрупнённых показателей (валидация, upsert, карантин)"
```

---

### Task 2: Импорт ресурсного каталога (`work_resources`)

**Files:**
- Modify: `backend/app/gosdata/core.py` (`_validate_work_resource`, `_upsert_work_resource`, `run_import_resources`)
- Test: `backend/tests/test_gosdata.py` (дополнить)

- [ ] **Step 1: Падающий тест**

Добавить в `backend/tests/test_gosdata.py`:
```python
def test_import_resources_inserts_and_validates(db):
    from app.gosdata.core import run_import_resources
    from app.models import WorkResource
    csv_text = """work_key,code,name,kind,unit,consumption,price,region,price_level,source,needs_review
frame_concrete,concrete_b25,Бетон B25,material,м³,1.02,31000,Астана,ССЦ-2026,ssc,false
frame_concrete,concreter_x,Бетонщик,labor,чел-ч,2.9,3600,Астана,ССЦ-2026,erer,false
frame_concrete,bad_unit,Кривой,labor,м³,1,100,Астана,ССЦ-2026,erer,false
"""
    report = run_import_resources(db, csv_text)
    assert report.inserted == 2 and report.skipped == 1  # labor с единицей м³ отбракован
    assert any("kind" in e or "единиц" in e for e in report.errors)
    row = db.query(WorkResource).filter_by(
        work_key="frame_concrete", code="concrete_b25",
        region="Астана", price_level="ССЦ-2026").first()
    assert row is not None and row.price == 31000 and row.source == "ssc"
```

- [ ] **Step 2: Запустить — упадёт**

Run: `cd backend && .venv/bin/python -m pytest tests/test_gosdata.py::test_import_resources_inserts_and_validates -q`
Expected: FAIL (`ImportError: run_import_resources`).

- [ ] **Step 3: Реализовать в `core.py`**

В шапку `core.py` добавить импорты:
```python
from ..calc.units import unit_known, unit_ok_for_kind
from ..models import GeneralizedIndicator, WorkResource
```
(заменив прежнюю строку `from ..calc.units import unit_known` и `from ..models import GeneralizedIndicator`).
В конец `core.py` добавить:
```python
_KINDS = {"material", "labor", "machine"}


def _validate_work_resource(row: dict) -> tuple[Optional[dict], Optional[str]]:
    work_key = (row.get("work_key") or "").strip()
    code = (row.get("code") or "").strip()
    if not work_key or not code:
        return None, "нет work_key/code"
    kind = (row.get("kind") or "").strip()
    if kind not in _KINDS:
        return None, f"некорректный kind: {kind!r}"
    unit = (row.get("unit") or "").strip()
    if not unit_ok_for_kind(unit, kind):
        return None, f"единица {unit!r} не подходит для вида {kind}"
    consumption = _to_float(row.get("consumption"))
    price = _to_float(row.get("price"))
    if consumption is None or consumption < 0:
        return None, f"некорректное consumption: {row.get('consumption')!r}"
    if price is None or price < 0:
        return None, f"некорректное price: {row.get('price')!r}"
    return {
        "work_key": work_key,
        "code": code,
        "official_code": (row.get("official_code") or "").strip(),
        "name": (row.get("name") or code).strip(),
        "kind": kind,
        "unit": unit,
        "consumption": consumption,
        "rank": (row.get("rank") or "").strip(),
        "price": price,
        "source": (row.get("source") or "import").strip(),
        "price_level": (row.get("price_level") or "import").strip(),
        "region": (row.get("region") or "KZ").strip(),
        "needs_review": _to_bool(row.get("needs_review"), default=False),
    }, None


def _upsert_work_resource(db: Session, c: dict) -> str:
    existing = db.scalar(
        select(WorkResource).where(
            WorkResource.work_key == c["work_key"],
            WorkResource.code == c["code"],
            WorkResource.region == c["region"],
            WorkResource.price_level == c["price_level"],
        )
    )
    if existing is None:
        db.add(WorkResource(**c))
        return "inserted"
    for k, v in c.items():
        setattr(existing, k, v)
    return "updated"


def run_import_resources(db: Session, csv_text: str) -> ImportReport:
    report = ImportReport(target="work_resources")
    reader = csv.DictReader(io.StringIO(csv_text))
    for i, row in enumerate(reader, start=2):
        clean, err = _validate_work_resource(row)
        if err:
            report.skipped += 1
            report.errors.append(f"строка {i}: {err}")
            continue
        result = _upsert_work_resource(db, clean)
        setattr(report, result, getattr(report, result) + 1)
    db.commit()
    return report
```

- [ ] **Step 4: Тест зелёный + полный сьют**

Run: `cd backend && .venv/bin/python -m pytest tests/test_gosdata.py -q`
Expected: PASS (4 passed).
Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: всё зелёное (~171).

- [ ] **Step 5: Commit**

```bash
git add backend/app/gosdata/core.py backend/tests/test_gosdata.py
git commit -m "feat(1c): импорт ресурсного каталога work_resources из CSV (валидация kind↔единица)"
```

---

### Task 3: CLI `python -m app.gosdata` + шаблоны CSV

**Files:**
- Create: `backend/app/gosdata/__main__.py`
- Create: `docs/gosdata-templates/generalized.csv`
- Create: `docs/gosdata-templates/work_resources.csv`
- Test: `backend/tests/test_gosdata.py` (дополнить — CLI main)

- [ ] **Step 1: Падающий тест CLI**

Добавить в `backend/tests/test_gosdata.py`:
```python
def test_cli_generalized(tmp_path):
    from app.gosdata.__main__ import main
    p = tmp_path / "g.csv"
    p.write_text("object_type,value,price_level\nСклад,175000,ССЦ-2026\n", encoding="utf-8")
    rc = main(["app.gosdata", "generalized", str(p)])
    assert rc == 0


def test_cli_bad_args():
    from app.gosdata.__main__ import main
    assert main(["app.gosdata"]) == 2
    assert main(["app.gosdata", "wat", "x.csv"]) == 2
```

- [ ] **Step 2: Запустить — упадёт**

Run: `cd backend && .venv/bin/python -m pytest tests/test_gosdata.py::test_cli_bad_args -q`
Expected: FAIL (нет `__main__.main`).

- [ ] **Step 3: `__main__.py` (CLI)**

Create `backend/app/gosdata/__main__.py`:
```python
"""CLI импорта: python -m app.gosdata <generalized|resources> <csv-файл>."""
from __future__ import annotations

import sys

from ..database import SessionLocal
from .core import run_import_generalized, run_import_resources

_RUNNERS = {"generalized": run_import_generalized, "resources": run_import_resources}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in _RUNNERS:
        print("Использование: python -m app.gosdata <generalized|resources> <csv-файл>")
        return 2
    target, path = argv[1], argv[2]
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        print(f"Не удалось прочитать файл: {exc}")
        return 2
    with SessionLocal() as db:
        report = _RUNNERS[target](db, text)
    print(report.summary())
    for e in report.errors[:20]:
        print("  ", e)
    if len(report.errors) > 20:
        print(f"  …и ещё {len(report.errors) - 20} ошибок")
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Шаблоны CSV (документация формата)**

Create `docs/gosdata-templates/generalized.csv`:
```csv
object_type,region,value,unit,price_level,source_code,source_url,needs_review
Жилой дом,Астана,310000,м²,ССЦ-2026,НДЦС РК 8.02-01-2025,,false
Офис,Астана,355000,м²,ССЦ-2026,НДЦС РК 8.02-01-2025,,false
```
Create `docs/gosdata-templates/work_resources.csv`:
```csv
work_key,code,official_code,name,kind,unit,consumption,rank,price,region,price_level,source,needs_review
frame_concrete,concrete_b25,,Бетон товарный B25,material,м³,1.02,,31000,Астана,ССЦ-2026,ssc,false
frame_concrete,concreter4,,Бетонщик 4 р.,labor,чел-ч,2.85,4,3600,Астана,ЕРЕР-2026,erer,false
```

- [ ] **Step 5: Тест зелёный + полный сьют + CLI-смоук**

Run: `cd backend && .venv/bin/python -m pytest tests/test_gosdata.py -q`
Expected: PASS (6 passed).
Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: всё зелёное (~173).
Smoke: `cd backend && .venv/bin/python -m app.gosdata generalized ../docs/gosdata-templates/generalized.csv`
Expected: строка отчёта `generalized_indicators: +N новых / ~M обновлено …` (rc 0).

- [ ] **Step 6: Commit**

```bash
git add backend/app/gosdata/__main__.py docs/gosdata-templates/ backend/tests/test_gosdata.py
git commit -m "feat(1c): CLI python -m app.gosdata + шаблоны CSV (формат импорта)"
```

---

## Self-Review

**1. Spec coverage (§4 пайплайн):** parsers (CSV DictReader), normalize (валидация единиц/видов/значений), load (upsert по натуральному ключу), CLI. ✓ Маппинг типов/ключей — пройдена как валидация + провенанс (авто-алиасов не вводим, YAGNI). Парсеры PDF/Excel — отложены (оператор экспортирует в CSV), зафиксировано в Scope.

**2. Placeholder scan:** полный код в каждом шаге; команды с ожиданиями. ✓

**3. Type consistency:** `run_import_*(db, csv_text) -> ImportReport`; `ImportReport` поля совпадают (inserted/updated/skipped/errors); upsert по тем же UniqueConstraint-ключам, что в моделях 1A/1B; `unit_ok_for_kind`/`unit_known` из 1A. ✓

**4. Краевые случаи:** битые строки → карантин (skipped + errors), не валят импорт; пустые/нечисловые/отрицательные значения; единица не из реестра / не подходит виду; идемпотентный upsert (повтор → updated); CLI: плохие аргументы → rc 2, ошибки чтения → rc 2, ошибки строк → rc 1.

**5. Честность/безопасность:** только локальные файлы, без сети/скрейпинга; провенанс из файла; `needs_review` из колонки (дефолт false = подтверждённые официальные). Импорт не выдаёт предварительное за официальное.

## Execution Handoff

План: `docs/superpowers/plans/2026-06-28-gos-catalog-units-plan1c-import.md`. 3 задачи. После 1C линия госкаталога закрыта: 1A (единицы+каталог в БД) → 1B (укрупнённый якорь) → 1C (импорт официальных данных). Остаётся операционное: получить реальные файлы и прогнать импорт.
