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
