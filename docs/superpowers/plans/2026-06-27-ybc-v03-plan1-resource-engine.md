# v0.3 План 1 — Ресурсный движок (схема + расчёт + recompute) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ввести ресурсный уровень сметы (материалы/труд/машины с нормами расхода) на 2 разделах — земляные работы и фундаменты/монолит — так, чтобы цена строки выводилась из ресурсов, а итог считался прежней формулой.

**Architecture:** Новая схема `ResourceLine` и поле `EstimateLine.resources`. Каталог норм — код-модуль `calc/resource_catalog.py` (без таблиц БД); при расчёте ресурсы снимаются снимком на строку, цена строки = свёртка состава (`rollup`). `recompute_estimate` для строк с ресурсами выводит цены из ресурсов (это и есть «редактируемые ресурсы»). Формула итога строки не меняется → совместимость с разделами/НДС/откатом/рекомендациями.

**Tech Stack:** Python 3.11, Pydantic v2, SQLAlchemy 2.0 (не затрагивается), pytest. Запуск тестов: `cd backend && .venv/bin/python -m pytest -q`.

**Контекст исполнителю (важно):**
- Все команды — из каталога `backend/`. Интерпретатор венва: `.venv/bin/python` (системный python3 = 3.9 и **не подходит**).
- `work_key` ресурсов = ключи объёмов из `app/calc/volumes.py` (`excavation`, `soil_removal`, `backfill`, `foundation_concrete`, `frame_concrete`, `rebar`, `formwork`).
- `foundation_concrete` и `frame_concrete` тарифицируются по плоскому ключу `concrete` (см. `PRICE_KEY_ALIAS` / `price_key_for` в `app/calc/pricing.py`).
- Снимок ресурсов кладётся в строку при расчёте; в БД отдельных таблиц **нет** (сериализуется внутри версии через `to_jsonable`).

---

## File Structure

- `backend/app/schemas.py` — **изменить**: новая модель `ResourceLine`; поле `EstimateLine.resources: list[ResourceLine] = []`.
- `backend/app/calc/resource_catalog.py` — **создать**: `ResourceSpec`, `COMPOSITIONS`, `rollup`, `snapshot_for`.
- `backend/app/calc/__init__.py` — **изменить**: реэкспорт `rollup`, `snapshot_for`.
- `backend/app/calc/estimate.py` — **изменить**: `build_estimate` (цепляет состав), `recompute_estimate` (выводит цены из ресурсов).
- `backend/tests/test_resource_catalog.py` — **создать**: тесты `rollup`/`snapshot_for`/sanity.
- `backend/tests/test_resource_engine.py` — **создать**: тесты build/recompute с ресурсами.

---

## Task 1: Схема `ResourceLine` и поле `EstimateLine.resources`

**Files:**
- Modify: `backend/app/schemas.py` (рядом с `class EstimateLine`, ~строки 102-114)
- Test: `backend/tests/test_resource_engine.py`

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_resource_engine.py`:

```python
from app.schemas import EstimateLine, ResourceLine


def test_estimate_line_defaults_to_no_resources():
    ln = EstimateLine(no="3.1", section="Фундаменты", title="Бетон",
                      unit="м³", quantity=10)
    assert ln.resources == []


def test_resource_line_roundtrips_through_estimate_line():
    r = ResourceLine(code="concrete_b25", name="Бетон B25",
                     kind="material", unit="м³", consumption=1.02, price=30000)
    ln = EstimateLine(no="3.1", section="Фундаменты", title="Бетон",
                      unit="м³", quantity=10, resources=[r])
    dumped = ln.model_dump()
    restored = EstimateLine(**dumped)
    assert restored.resources[0].code == "concrete_b25"
    assert restored.resources[0].consumption == 1.02
    assert restored.resources[0].kind == "material"
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_resource_engine.py -q`
Expected: FAIL — `ImportError: cannot import name 'ResourceLine'`.

- [ ] **Step 3: Реализовать схему**

В `backend/app/schemas.py` **перед** `class EstimateLine(BaseModel):` вставить:

```python
class ResourceLine(BaseModel):
    code: str
    name: str
    kind: str  # "material" | "labor" | "machine"
    unit: str
    consumption: float
    price: float = 0.0
```

В `class EstimateLine(BaseModel):` после поля `needs_review: bool = False` добавить:

```python
    resources: list[ResourceLine] = []
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_resource_engine.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Коммит**

```bash
git add backend/app/schemas.py backend/tests/test_resource_engine.py
git commit -m "feat(schemas): ResourceLine + EstimateLine.resources"
```

---

## Task 2: Каталог ресурсов `resource_catalog.py` (`rollup`, `snapshot_for`)

**Files:**
- Create: `backend/app/calc/resource_catalog.py`
- Modify: `backend/app/calc/__init__.py`
- Test: `backend/tests/test_resource_catalog.py`

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_resource_catalog.py`:

```python
from app.calc.resource_catalog import COMPOSITIONS, rollup, snapshot_for
from app.calc.pricing import PRICES, price_key_for


def test_rollup_sums_by_kind():
    res = snapshot_for("foundation_concrete")
    material, labor, machine = rollup(res)
    assert material > 0 and labor > 0 and machine > 0
    # свёртка совпадает с ручной суммой
    exp_m = sum(r.consumption * r.price for r in res if r.kind == "material")
    assert abs(material - exp_m) < 1e-6


def test_rollup_empty_is_zero():
    assert rollup([]) == (0, 0, 0)


def test_snapshot_for_unknown_key_is_empty():
    assert snapshot_for("does_not_exist") == []


def test_snapshot_returns_independent_copies():
    a = snapshot_for("rebar")
    b = snapshot_for("rebar")
    a[0].price = 999999
    assert b[0].price != 999999  # снимки не делят состояние


def test_compositions_within_sanity_band_of_flat_prices():
    # свёртка состава ≈ плоская цена PRICES (±40%), чтобы итоги смет не «прыгнули»
    for key in COMPOSITIONS:
        material, labor, machine = rollup(snapshot_for(key))
        composed = material + labor + machine
        flat = PRICES[price_key_for(key)]
        flat_total = flat.material + flat.labor + flat.machine
        assert 0.6 * flat_total <= composed <= 1.4 * flat_total, (
            f"{key}: composed={composed:.0f} flat={flat_total:.0f}"
        )
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_resource_catalog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.calc.resource_catalog'`.

- [ ] **Step 3: Реализовать каталог**

Создать `backend/app/calc/resource_catalog.py`:

```python
"""Ресурсный состав работ (класс 3): work_key → ресурсы с нормами расхода.

Нормы расхода и цены ресурсов — ОРИЕНТИРОВОЧНЫЕ показатели РК (Астана, 2026),
требуют проверки сметчиком; это НЕ лицензированные сборники ГЭСН/СН РК. Свёртка
состава работы откалибрована к плоскому справочнику PRICES (sanity ±40%), чтобы
переход на ресурсный расчёт не менял порядок итогов."""
from __future__ import annotations

from dataclasses import dataclass

from ..schemas import ResourceLine


@dataclass(frozen=True)
class ResourceSpec:
    code: str
    name: str
    kind: str        # "material" | "labor" | "machine"
    unit: str
    consumption: float  # норма расхода на ЕДИНИЦУ работы
    price: float        # цена ресурса за его единицу


# work_key (из volumes.py) → список ресурсов на единицу работы.
COMPOSITIONS: dict[str, list[ResourceSpec]] = {
    # ── Земляные работы (на 1 м³) ──
    "excavation": [
        ResourceSpec("excavator_1m3", "Экскаватор одноковшовый 1 м³", "machine", "маш-ч", 0.022, 22000),
        ResourceSpec("operator_exc", "Машинист экскаватора 6 р.", "labor", "чел-ч", 0.022, 4200),
        ResourceSpec("laborer_earth", "Землекоп 2 р. (доработка вручную)", "labor", "чел-ч", 0.52, 2500),
    ],
    "soil_removal": [
        ResourceSpec("dump_truck", "Самосвал 10 т", "machine", "маш-ч", 0.05, 16000),
        ResourceSpec("loader_soil", "Погрузчик фронтальный", "machine", "маш-ч", 0.012, 18000),
        ResourceSpec("operator_truck", "Водитель самосвала", "labor", "чел-ч", 0.05, 3500),
        ResourceSpec("laborer_soil", "Подсобный рабочий 2 р.", "labor", "чел-ч", 0.13, 2500),
    ],
    "backfill": [
        ResourceSpec("bulldozer", "Бульдозер", "machine", "маш-ч", 0.008, 17000),
        ResourceSpec("rammer", "Виброплита/трамбовка", "machine", "маш-ч", 0.05, 1200),
        ResourceSpec("laborer_backfill", "Землекоп 2 р.", "labor", "чел-ч", 0.32, 2500),
    ],
    # ── Фундаменты и монолит ЖБ ──
    "foundation_concrete": [   # на 1 м³ бетона фундамента
        ResourceSpec("concrete_b25", "Бетон товарный B25 (с доставкой)", "material", "м³", 1.02, 30000),
        ResourceSpec("pump", "Бетононасос", "machine", "маш-ч", 0.10, 18000),
        ResourceSpec("vibrator", "Вибратор глубинный", "machine", "маш-ч", 0.12, 1500),
        ResourceSpec("crane_concrete", "Кран на бетонировании", "machine", "маш-ч", 0.16, 20000),
        ResourceSpec("concreter", "Бетонщик 4 р.", "labor", "чел-ч", 2.8, 3500),
    ],
    "frame_concrete": [        # на 1 м³ бетона каркаса
        ResourceSpec("concrete_b25", "Бетон товарный B25 (с доставкой)", "material", "м³", 1.02, 30000),
        ResourceSpec("pump", "Бетононасос", "machine", "маш-ч", 0.14, 18000),
        ResourceSpec("vibrator", "Вибратор глубинный", "machine", "маш-ч", 0.15, 1500),
        ResourceSpec("crane_frame", "Кран башенный (подача бетона)", "machine", "маш-ч", 0.13, 20000),
        ResourceSpec("concreter", "Бетонщик 4 р.", "labor", "чел-ч", 2.85, 3500),
    ],
    "rebar": [                 # на 1 т арматуры
        ResourceSpec("rebar_a500", "Арматура A500C (прокат)", "material", "т", 1.02, 340000),
        ResourceSpec("wire_binding", "Проволока вязальная", "material", "кг", 12.0, 600),
        ResourceSpec("steelfixer", "Арматурщик 4 р.", "labor", "чел-ч", 28.0, 3500),
        ResourceSpec("crane_rebar", "Кран на монтаже арматуры", "machine", "маш-ч", 0.4, 20000),
    ],
    "formwork": [              # на 1 м² опалубки
        ResourceSpec("form_panel", "Щит опалубки (с оборачиваемостью)", "material", "м²", 0.10, 12000),
        ResourceSpec("form_fasteners", "Крепёж/стяжки опалубки", "material", "компл", 0.2, 1500),
        ResourceSpec("form_oil", "Смазка опалубки", "material", "кг", 0.10, 800),
        ResourceSpec("carpenter_form", "Плотник-опалубщик 4 р.", "labor", "чел-ч", 0.9, 3300),
    ],
}


def rollup(resources: list[ResourceLine]) -> tuple[float, float, float]:
    """(материал, труд, машины) за единицу работы = Σ consumption×price по виду."""
    material = sum(r.consumption * r.price for r in resources if r.kind == "material")
    labor = sum(r.consumption * r.price for r in resources if r.kind == "labor")
    machine = sum(r.consumption * r.price for r in resources if r.kind == "machine")
    return material, labor, machine


def snapshot_for(work_key: str) -> list[ResourceLine]:
    """Свежий снимок ResourceLine для работы (пустой список, если состава нет)."""
    specs = COMPOSITIONS.get(work_key)
    if not specs:
        return []
    return [
        ResourceLine(code=s.code, name=s.name, kind=s.kind, unit=s.unit,
                     consumption=s.consumption, price=s.price)
        for s in specs
    ]
```

В `backend/app/calc/__init__.py` добавить реэкспорт. Заменить содержимое файла на:

```python
"""Детерминированный расчёт: геометрия → объёмы → смета."""

from .estimate import build_estimate, recompute_estimate
from .recommendations import (
    REC_SECTION,
    applicable_recommendations,
    build_recommendation_line,
)
from .resource_catalog import COMPOSITIONS, rollup, snapshot_for

__all__ = [
    "build_estimate",
    "recompute_estimate",
    "REC_SECTION",
    "applicable_recommendations",
    "build_recommendation_line",
    "COMPOSITIONS",
    "rollup",
    "snapshot_for",
]
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `.venv/bin/python -m pytest tests/test_resource_catalog.py -q`
Expected: PASS (5 passed). Если sanity-тест падает на каком-то ключе — поправить расход/цену в его составе, не трогая тест.

- [ ] **Step 5: Коммит**

```bash
git add backend/app/calc/resource_catalog.py backend/app/calc/__init__.py backend/tests/test_resource_catalog.py
git commit -m "feat(calc): resource_catalog с rollup/snapshot_for (земляные+фундаменты)"
```

---

## Task 3: Подключить состав в `build_estimate`

**Files:**
- Modify: `backend/app/calc/estimate.py` (цикл по разделам, ~строки 88-111)
- Test: `backend/tests/test_resource_engine.py`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `backend/tests/test_resource_engine.py`:

```python
from app.calc import build_estimate, rollup
from app.calc.estimate import recompute_estimate  # noqa: F401 (для Task 4)
from app.norms.resolver import resolve_norm_profile
from app.database import SessionLocal
from app.schemas import BuildingInput
from app.seed import run_seed


def _build():
    run_seed()
    db = SessionLocal()
    try:
        inp = BuildingInput(object_type="Жилой дом", demo_mode=True, use_search=False)
        profile = resolve_norm_profile(db, inp)
        return inp, build_estimate(db, inp, profile)
    finally:
        db.close()


def test_concrete_line_has_resources_and_price_from_rollup():
    _, res = _build()
    line = next(l for l in res.lines if l.title == "Бетон фундамента")
    assert line.resources, "у строки бетона должен быть ресурсный состав"
    material, labor, machine = rollup(line.resources)
    assert line.material_price == material
    assert line.labor_price == labor
    assert line.machine_price == machine
    assert line.total == round(line.quantity * (material + labor + machine))


def test_line_without_composition_has_no_resources():
    _, res = _build()
    # «Кровля» (roof) в Плане 1 без состава → старое поведение
    line = next(l for l in res.lines if l.title == "Кровля")
    assert line.resources == []
    assert line.total > 0
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_resource_engine.py::test_concrete_line_has_resources_and_price_from_rollup -q`
Expected: FAIL — `AssertionError` (resources пуст / цены из flat PRICES не равны rollup).

- [ ] **Step 3: Реализовать интеграцию**

В `backend/app/calc/estimate.py` добавить импорт вверху (рядом с `from .pricing import get_price`):

```python
from .resource_catalog import rollup, snapshot_for
```

В `build_estimate`, в теле цикла `for key in keys:` заменить блок вычисления цены и создания строки. Текущий код:

```python
            price = get_price(db, key, region)
            unit_cost = price.material + price.labor + price.machine
            line_total = round(vol.quantity * unit_cost)
            sub_index += 1
            lines.append(
                EstimateLine(
                    no=f"{number}.{sub_index}",
                    section=title,
                    title=vol.title,
                    norm=vol.norm,
                    unit=vol.unit,
                    quantity=vol.quantity,
                    material_price=price.material,
                    labor_price=price.labor,
                    machine_price=price.machine,
                    total=line_total,
                    needs_review=vol.needs_review,
                    comment="требует проверки сметчиком" if vol.needs_review else "",
                )
            )
            section_sum += line_total
```

заменить на:

```python
            resources = snapshot_for(key)
            if resources:
                material_price, labor_price, machine_price = rollup(resources)
            else:
                price = get_price(db, key, region)
                material_price, labor_price, machine_price = (
                    price.material, price.labor, price.machine
                )
            unit_cost = material_price + labor_price + machine_price
            line_total = round(vol.quantity * unit_cost)
            sub_index += 1
            lines.append(
                EstimateLine(
                    no=f"{number}.{sub_index}",
                    section=title,
                    title=vol.title,
                    norm=vol.norm,
                    unit=vol.unit,
                    quantity=vol.quantity,
                    material_price=material_price,
                    labor_price=labor_price,
                    machine_price=machine_price,
                    total=line_total,
                    needs_review=vol.needs_review,
                    comment="требует проверки сметчиком" if vol.needs_review else "",
                    resources=resources,
                )
            )
            section_sum += line_total
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.venv/bin/python -m pytest tests/test_resource_engine.py -q`
Expected: PASS (все тесты файла).

- [ ] **Step 5: Коммит**

```bash
git add backend/app/calc/estimate.py backend/tests/test_resource_engine.py
git commit -m "feat(calc): build_estimate цепляет ресурсный состав и считает цену из rollup"
```

---

## Task 4: Вывод цен из ресурсов в `recompute_estimate` (редактируемые ресурсы)

**Files:**
- Modify: `backend/app/calc/estimate.py` (функция `recompute_estimate`, цикл по `core`, ~строки 217-224)
- Test: `backend/tests/test_resource_engine.py`

- [ ] **Step 1: Дописать падающие тесты**

Добавить в `backend/tests/test_resource_engine.py`:

```python
def test_recompute_is_noop_with_resources():
    inp, res = _build()
    lines = [l.model_copy(deep=True) for l in res.lines]
    out = recompute_estimate(res, lines, inp)
    assert [round(l.total) for l in out.lines] == [round(l.total) for l in res.lines]
    assert out.totals.grand_total == res.totals.grand_total


def test_editing_resource_consumption_changes_line_and_grand_total():
    inp, res = _build()
    lines = [l.model_copy(deep=True) for l in res.lines]
    line = next(l for l in lines if l.title == "Бетон фундамента")
    old_material_price = line.material_price  # ЗАХВАТИТЬ до recompute (мутирует на месте)
    conc = next(r for r in line.resources if r.code == "concrete_b25")
    conc.consumption = conc.consumption * 2  # вдвое больше бетона
    out = recompute_estimate(res, lines, inp)
    out_line = next(l for l in out.lines if l.title == "Бетон фундамента")
    # цена материала строки = новая свёртка из ресурсов
    exp_m = sum(r.consumption * r.price for r in out_line.resources if r.kind == "material")
    assert out_line.material_price == exp_m
    assert out_line.material_price > old_material_price
    assert out.totals.grand_total > res.totals.grand_total


def test_editing_resource_price_changes_total():
    inp, res = _build()
    lines = [l.model_copy(deep=True) for l in res.lines]
    line = next(l for l in lines if l.title == "Арматура")
    steel = next(r for r in line.resources if r.code == "rebar_a500")
    steel.price = steel.price + 100000
    out = recompute_estimate(res, lines, inp)
    out_line = next(l for l in out.lines if l.title == "Арматура")
    exp_m = sum(r.consumption * r.price for r in out_line.resources if r.kind == "material")
    assert out_line.material_price == exp_m
    assert out.totals.grand_total > res.totals.grand_total


def test_changing_work_quantity_scales_line_total_from_resources():
    inp, res = _build()
    lines = [l.model_copy(deep=True) for l in res.lines]
    line = next(l for l in lines if l.title == "Бетон фундамента")
    unit_cost = line.material_price + line.labor_price + line.machine_price
    line.quantity = line.quantity + 5
    out = recompute_estimate(res, lines, inp)
    out_line = next(l for l in out.lines if l.title == "Бетон фундамента")
    assert out_line.total == round(out_line.quantity * unit_cost)
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `.venv/bin/python -m pytest tests/test_resource_engine.py -k "recompute or resource_consumption or resource_price or work_quantity" -q`
Expected: FAIL для тестов правки ресурсов (цены строки берутся как есть, не из ресурсов). `test_recompute_is_noop_with_resources` может пройти и до правки — это нормально.

- [ ] **Step 3: Реализовать вывод цен из ресурсов**

В `backend/app/calc/estimate.py`, в `recompute_estimate`, в цикле `for ln in core:` заменить начало тела. Текущий код:

```python
    for ln in core:
        unit_cost = ln.material_price + ln.labor_price + ln.machine_price
        ln.total = round(ln.quantity * unit_cost)
```

заменить на:

```python
    for ln in core:
        if ln.resources:
            ln.material_price, ln.labor_price, ln.machine_price = rollup(ln.resources)
        unit_cost = ln.material_price + ln.labor_price + ln.machine_price
        ln.total = round(ln.quantity * unit_cost)
```

(Импорт `rollup` уже добавлен в Task 3.)

- [ ] **Step 4: Запустить весь набор — убедиться, что всё зелёное**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — все тесты (прежние 55 + новые из Плана 1). В частности `tests/test_recompute.py` (старый no-op) остаётся зелёным.

- [ ] **Step 5: Коммит**

```bash
git add backend/app/calc/estimate.py backend/tests/test_resource_engine.py
git commit -m "feat(calc): recompute выводит цены строки из ресурсов (редактируемые ресурсы)"
```

---

## Definition of Done (План 1)

- `ResourceLine` и `EstimateLine.resources` есть; версии сериализуются с ресурсами (round-trip тест зелёный).
- Земляные (excavation/soil_removal/backfill) и фундаментные (foundation_concrete/frame_concrete/rebar/formwork) строки несут ресурсный состав; цена строки = свёртка состава.
- Правка расхода/цены ресурса и объёма работы корректно меняет итоги через `recompute_estimate`.
- Разделы без состава работают как прежде; `build_estimate → recompute` без правок — no-op.
- Весь набор тестов зелёный; sanity-полоса ±40% к PRICES соблюдена для разделов Плана 1.
