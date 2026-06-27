# v0.3 План 2 — Наполнение каталога ресурсов (все разделы) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить ресурсный состав для всех оставшихся объёмных работ (16 ключей: перегородки, изоляция, кровля, фасад, остекление, отделка, инженерные сети, благоустройство), чтобы вся смета считалась на ресурсном уровне.

**Architecture:** Только данные — расширяем `COMPOSITIONS` в `calc/resource_catalog.py`. Движок (`build_estimate`/`recompute_estimate`) из Плана 1 уже подхватывает любой ключ с составом, поэтому код движка не трогаем. Добавляем тест полноты (каждый объёмный `work_key` имеет состав); существующий sanity-тест (±40% к `PRICES`) автоматически покрывает новые ключи.

**Tech Stack:** Python 3.11, pytest. Все команды из `backend/`, интерпретатор `.venv/bin/python`.

**Контекст исполнителю:**
- Числа в составах — ОРИЕНТИРОВОЧНЫЕ показатели РК, откалиброваны так, чтобы свёртка была в пределах ±40% от плоской цены `PRICES` (иначе sanity-тест Плана 1 упадёт).
- Расход (`consumption`) — на ЕДИНИЦУ работы (для инженерных систем единица — м² общей площади; для отделки/кровли/фасада — м²; для перегородок — м²).
- НЕ менять код `estimate.py`, `__init__.py`, схемы — только данные в `resource_catalog.py` и новый тест.

---

## File Structure

- `backend/app/calc/resource_catalog.py` — **изменить**: добавить 16 ключей в `COMPOSITIONS`.
- `backend/tests/test_resource_catalog.py` — **изменить**: добавить тест полноты.

---

## Task 1: Состав по всем оставшимся разделам + тест полноты

**Files:**
- Modify: `backend/app/calc/resource_catalog.py` (dict `COMPOSITIONS`)
- Test: `backend/tests/test_resource_catalog.py`

- [ ] **Step 1: Написать падающий тест полноты**

APPEND в конец `backend/tests/test_resource_catalog.py`:

```python
def test_every_volume_work_has_a_composition():
    from app.calc.volumes import compute_volumes
    from app.norms.resolver import resolve_norm_profile
    from app.schemas import BuildingInput
    from app.database import SessionLocal
    from app.seed import run_seed

    run_seed()
    db = SessionLocal()
    try:
        inp = BuildingInput(object_type="Жилой дом", demo_mode=True, use_search=False)
        profile = resolve_norm_profile(db, inp)
        volumes = compute_volumes(inp, profile)
        missing = [k for k in volumes if k not in COMPOSITIONS]
        assert not missing, f"нет ресурсного состава для: {missing}"
    finally:
        db.close()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `.venv/bin/python -m pytest tests/test_resource_catalog.py::test_every_volume_work_has_a_composition -q`
Expected: FAIL — `AssertionError: нет ресурсного состава для: [...]` (список из 16 ключей: partitions, waterproofing_foundation, insulation_foundation, insulation_walls, insulation_roof, roof, facade, glazing, screed, wall_finish, ceiling_finish, hvac, plumbing, electrical, low_current, landscaping).

- [ ] **Step 3: Добавить составы**

В `backend/app/calc/resource_catalog.py`, в dict `COMPOSITIONS`, ПЕРЕД закрывающей `}` добавить следующие записи (после существующего ключа `"formwork"`):

```python
    # ── Кладка перегородок (на 1 м²) ──
    "partitions": [
        ResourceSpec("aerated_block", "Газоблок D500", "material", "м³", 0.09, 22000),
        ResourceSpec("masonry_glue", "Клей/раствор кладочный", "material", "кг", 8.0, 120),
        ResourceSpec("mason", "Каменщик 4 р.", "labor", "чел-ч", 0.9, 2900),
    ],
    # ── Гидро/теплоизоляция (на 1 м²) ──
    "waterproofing_foundation": [
        ResourceSpec("waterproof_roll", "Гидроизоляция рулонная (2 слоя)", "material", "м²", 1.15, 1100),
        ResourceSpec("primer_bit", "Праймер битумный", "material", "кг", 0.3, 700),
        ResourceSpec("insulator_wp", "Изолировщик 4 р.", "labor", "чел-ч", 0.32, 2600),
    ],
    "insulation_foundation": [
        ResourceSpec("xps", "Плита ЭППС (100 мм)", "material", "м³", 0.1, 28000),
        ResourceSpec("xps_fix", "Крепёж/клей ЭППС", "material", "компл", 0.2, 1000),
        ResourceSpec("insulator_fnd", "Изолировщик 3 р.", "labor", "чел-ч", 0.26, 2600),
    ],
    "insulation_walls": [
        ResourceSpec("mineral_wool_w", "Минвата фасадная (120 мм)", "material", "м³", 0.12, 18000),
        ResourceSpec("membrane_fix", "Мембрана + крепёж", "material", "компл", 0.3, 1200),
        ResourceSpec("insulator_w", "Изолировщик 3 р.", "labor", "чел-ч", 0.3, 2600),
    ],
    "insulation_roof": [
        ResourceSpec("mineral_wool_r", "Минвата кровельная (150 мм)", "material", "м³", 0.15, 13000),
        ResourceSpec("insulator_r", "Изолировщик 3 р.", "labor", "чел-ч", 0.27, 2600),
    ],
    # ── Кровля (на 1 м²) ──
    "roof": [
        ResourceSpec("roof_membrane", "Мягкая кровля наплавляемая (2 слоя)", "material", "м²", 2.3, 1100),
        ResourceSpec("primer_roof", "Праймер", "material", "кг", 0.3, 700),
        ResourceSpec("roofer", "Кровельщик 4 р.", "labor", "чел-ч", 0.55, 2900),
    ],
    # ── Фасад (на 1 м²) ──
    "facade": [
        ResourceSpec("facade_system", "Вентфасад: плита, утеплитель, подсистема", "material", "компл", 1.0, 8000),
        ResourceSpec("facade_installer", "Монтажник фасадных систем 4 р.", "labor", "чел-ч", 1.35, 3000),
    ],
    # ── Окна, витражи (на 1 м²) ──
    "glazing": [
        ResourceSpec("window_pvc", "Окно ПВХ / витраж (с фурнитурой)", "material", "м²", 1.0, 24500),
        ResourceSpec("glazier", "Монтажник светопрозрачных конструкций", "labor", "чел-ч", 1.6, 3100),
    ],
    # ── Отделка (на 1 м²) ──
    "screed": [
        ResourceSpec("screed_mix", "Пескобетон/ЦПС М300", "material", "м³", 0.05, 28000),
        ResourceSpec("screed_add", "Фиброволокно/добавки", "material", "кг", 0.1, 1000),
        ResourceSpec("screeder", "Бетонщик-отделочник 3 р.", "labor", "чел-ч", 0.35, 2900),
    ],
    "wall_finish": [
        ResourceSpec("plaster_set", "Штукатурка, шпатлёвка, грунт, краска", "material", "компл", 1.0, 1750),
        ResourceSpec("finisher_wall", "Маляр-штукатур 4 р.", "labor", "чел-ч", 0.75, 2950),
    ],
    "ceiling_finish": [
        ResourceSpec("ceiling_set", "Шпатлёвка, грунт, краска потолка", "material", "компл", 1.0, 780),
        ResourceSpec("finisher_ceil", "Маляр 4 р.", "labor", "чел-ч", 0.35, 2950),
    ],
    # ── Инженерные системы (на 1 м² общей площади) ──
    "hvac": [
        ResourceSpec("hvac_equipment", "Оборудование ОВиК, воздуховоды, трубы", "material", "компл", 1.0, 2950),
        ResourceSpec("hvac_installer", "Монтажник систем вентиляции 4 р.", "labor", "чел-ч", 0.5, 3000),
    ],
    "plumbing": [
        ResourceSpec("plumbing_mat", "Трубы, фитинги, сантехприборы", "material", "компл", 1.0, 1950),
        ResourceSpec("plumber", "Слесарь-сантехник 4 р.", "labor", "чел-ч", 0.33, 3000),
    ],
    "electrical": [
        ResourceSpec("electrical_mat", "Кабель, щиты, розетки, светильники", "material", "компл", 1.0, 3450),
        ResourceSpec("electrician", "Электромонтажник 4 р.", "labor", "чел-ч", 0.65, 3050),
    ],
    "low_current": [
        ResourceSpec("low_current_mat", "Кабель СКС, слаботочное оборудование", "material", "компл", 1.0, 980),
        ResourceSpec("lc_installer", "Монтажник слаботочных систем", "labor", "чел-ч", 0.17, 3000),
    ],
    # ── Благоустройство (на 1 м²) ──
    "landscaping": [
        ResourceSpec("landscape_mat", "Покрытие, бордюр, грунт, наружные сети", "material", "компл", 1.0, 1950),
        ResourceSpec("landscaper", "Рабочий благоустройства 3 р.", "labor", "чел-ч", 0.4, 2600),
    ],
```

- [ ] **Step 4: Запустить тест полноты + sanity + весь набор**

Run: `.venv/bin/python -m pytest tests/test_resource_catalog.py -q`
Expected: PASS — в т.ч. `test_every_volume_work_has_a_composition` и `test_compositions_within_sanity_band_of_flat_prices` (теперь итерирует все ключи).
Если sanity упадёт на каком-то новом ключе — подправить расход/цену этого ключа (НЕ тест), пока свёртка не попадёт в ±40% от `PRICES[price_key_for(key)]`.

Run: `.venv/bin/python -m pytest -q`
Expected: всё зелёное (было 68; теперь 69).

- [ ] **Step 5: Коммит**

```bash
cd /Users/eek/Docs/kpro_case/mvp1/repo/k-pro-building
git add backend/app/calc/resource_catalog.py backend/tests/test_resource_catalog.py
git commit -m "feat(calc): ресурсный состав по всем разделам + тест полноты каталога"
```

---

## Definition of Done (План 2)

- Каждый объёмный `work_key` (23 из `volumes.py`) имеет ресурсный состав.
- `test_every_volume_work_has_a_composition` зелёный.
- Sanity ±40% к `PRICES` соблюдён для всех ключей.
- Весь набор тестов зелёный; вся смета считается на ресурсном уровне.
