"""Дефолтные нормативные коэффициенты.

Эти значения — укрупнённые показатели по практике строительства РК. Они
гарантируют, что расчёт всегда завершится, даже если LLM недоступен. Любое
значение может быть уточнено/подтверждено правилами из БД или извлечением LLM;
неподтверждённые помечаются как требующие проверки сметчиком.
"""
from __future__ import annotations

from ..schemas import BuildingInput, NormParam

# Метаданные категорий: единица измерения и человекочитаемый ярлык.
CATEGORY_META: dict[str, tuple[str, str]] = {
    "foundation_concrete_per_area": ("м³/м²", "Расход бетона фундамента на м² застройки"),
    "frame_concrete_per_area": ("м³/м²", "Расход бетона каркаса на м² общей площади"),
    "rebar_kg_per_m3": ("кг/м³", "Расход арматуры на м³ бетона"),
    "formwork_m2_per_m3": ("м²/м³", "Площадь опалубки на м³ бетона"),
    "partition_m2_per_area": ("м²/м²", "Перегородки на м² общей площади"),
    "partition_thickness_m": ("м", "Толщина перегородок"),
    "glazing_share_of_facade": ("доля", "Доля остекления в площади фасада"),
    "excavation_depth_m": ("м", "Глубина котлована"),
    "backfill_share": ("доля", "Доля обратной засыпки от выемки"),
    "wall_insulation_thickness_m": ("м", "Толщина теплоизоляции стен"),
    "roof_insulation_thickness_m": ("м", "Толщина теплоизоляции кровли"),
    "finishing_factor": ("коэф.", "Коэффициент объёма отделки по классу"),
    "engineering_factor": ("коэф.", "Коэффициент объёма инженерных систем по классу"),
}


def _frame_concrete(structure: str) -> float:
    s = structure.lower()
    if "монолит" in s:
        return 0.30
    if "сборный" in s:
        return 0.20
    if "каркас" in s:
        return 0.18
    if "металлокаркас" in s:
        return 0.08
    if "кирпич" in s or "газоблок" in s:
        return 0.10
    return 0.20


def _foundation_concrete(foundation: str, basement: bool) -> tuple[float, bool]:
    """Расход бетона фундамента (м³ на м² застройки) + флаг 'требует проверки'."""
    f = foundation.lower()
    if "плита" in f:
        return (0.55 if not basement else 0.65), False
    if "ленточн" in f:
        return 0.35, False
    if "свайн" in f:
        return 0.25, False
    if "столбчат" in f:
        return 0.15, False
    return 0.40, True  # «Определить по проекту»


def _rebar(structure: str, foundation: str) -> float:
    base = 110.0 if "монолит" in structure.lower() else 85.0
    if "плита" in foundation.lower():
        base += 10.0
    return base


def _glazing(object_type: str) -> float:
    o = object_type.lower()
    if "офис" in o or "коммерч" in o:
        return 0.35
    if "склад" in o or "производ" in o:
        return 0.10
    if "жил" in o:
        return 0.18
    return 0.22


def _excavation_depth(foundation: str, basement: bool) -> float:
    if basement:
        return 3.2
    f = foundation.lower()
    if "плита" in f:
        return 1.5
    if "ленточн" in f:
        return 1.8
    if "свайн" in f:
        return 1.0
    if "столбчат" in f:
        return 1.4
    return 1.5


def _finishing_factor(finish_level: str) -> tuple[float, bool]:
    f = finish_level.lower()
    if "без отделки" in f:
        return 0.0, False
    if "черновая" in f:
        return 0.6, False
    if "white" in f:
        return 0.8, False
    if "стандарт" in f:
        return 1.0, False
    if "бизнес" in f:
        return 1.35, False
    return 1.0, True


def _engineering_factor(level: str) -> tuple[float, bool]:
    l = level.lower()
    if "базов" in l:
        return 0.8, False
    if "стандарт" in l:
        return 1.0, False
    if "повышен" in l:
        return 1.3, False
    return 1.0, True  # «Определить по проекту»


def resolve_defaults(inp: BuildingInput) -> dict[str, NormParam]:
    """Полный набор дефолтных коэффициентов под конкретный объект."""
    fnd_concrete, fnd_review = _foundation_concrete(inp.foundation_type, inp.basement)
    fin_factor, fin_review = _finishing_factor(inp.finish_level)
    eng_factor, eng_review = _engineering_factor(inp.engineering_level)

    def p(category: str, value: float, *, review: bool = False, note: str = "") -> NormParam:
        unit, _label = CATEGORY_META.get(category, ("", ""))
        return NormParam(
            category=category,
            value=value,
            unit=unit,
            source="default",
            confidence=0.4,
            needs_review=review,
            note=note or "укрупнённый показатель по практике РК",
        )

    return {
        "foundation_concrete_per_area": p(
            "foundation_concrete_per_area", fnd_concrete, review=fnd_review
        ),
        "frame_concrete_per_area": p(
            "frame_concrete_per_area", _frame_concrete(inp.structure_type)
        ),
        "rebar_kg_per_m3": p(
            "rebar_kg_per_m3", _rebar(inp.structure_type, inp.foundation_type)
        ),
        "formwork_m2_per_m3": p("formwork_m2_per_m3", 2.5),
        "partition_m2_per_area": p(
            "partition_m2_per_area",
            0.7 if "жил" in inp.object_type.lower() else 0.5,
        ),
        "partition_thickness_m": p("partition_thickness_m", 0.12),
        "glazing_share_of_facade": p(
            "glazing_share_of_facade", _glazing(inp.object_type)
        ),
        "excavation_depth_m": p(
            "excavation_depth_m", _excavation_depth(inp.foundation_type, inp.basement)
        ),
        "backfill_share": p("backfill_share", 0.5),
        "wall_insulation_thickness_m": p("wall_insulation_thickness_m", 0.1),
        "roof_insulation_thickness_m": p("roof_insulation_thickness_m", 0.15),
        "finishing_factor": p("finishing_factor", fin_factor, review=fin_review),
        "engineering_factor": p("engineering_factor", eng_factor, review=eng_review),
    }
