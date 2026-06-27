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
