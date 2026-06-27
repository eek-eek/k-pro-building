"""Расчёт объёмов по разделам из геометрии и нормативного профиля."""
from __future__ import annotations

from ..schemas import BuildingInput, NormProfile, VolumeItem
from .geometry import Geometry, derive


def _norm_label(profile: NormProfile, category: str) -> tuple[str, bool]:
    """Ярлык нормы (документ/дефолт) и флаг 'требует проверки' для категории."""
    p = profile.params.get(category)
    if p is None:
        return "дефолт РК", True
    if p.document_code:
        return p.document_code, p.needs_review
    if p.source == "default":
        return "укрупн. показатель РК", p.needs_review
    return f"норма ({p.source})", p.needs_review


def compute_volumes(
    inp: BuildingInput, profile: NormProfile, geo: Geometry | None = None
) -> dict[str, VolumeItem]:
    geo = geo or derive(inp)
    out: dict[str, VolumeItem] = {}

    def add(
        key: str,
        title: str,
        unit: str,
        quantity: float,
        formula: str,
        norm_category: str | None,
    ) -> None:
        if norm_category:
            norm, review = _norm_label(profile, norm_category)
        else:
            norm, review = "геометрия", False
        out[key] = VolumeItem(
            key=key,
            title=title,
            unit=unit,
            quantity=round(quantity, 2),
            formula=formula,
            norm=norm,
            needs_review=review,
        )

    pv = profile.value  # сокращение

    # ── Земляные работы ──
    exc_depth = pv("excavation_depth_m", 1.5)
    excavation = geo.build_area * exc_depth
    backfill = excavation * pv("backfill_share", 0.5)
    removal = max(excavation - backfill, 0.0)
    add("excavation", "Разработка грунта котлована", "м³", excavation,
        f"{geo.build_area:.0f} м² застройки × {exc_depth:g} м глубина",
        "excavation_depth_m")
    add("soil_removal", "Вывоз грунта", "м³", removal,
        f"выемка {excavation:.0f} − засыпка {backfill:.0f}", "backfill_share")
    add("backfill", "Обратная засыпка", "м³", backfill,
        f"{excavation:.0f} × {pv('backfill_share', 0.5):g}", "backfill_share")

    # ── Бетон и арматура ──
    fnd_concrete = geo.build_area * pv("foundation_concrete_per_area", 0.5)
    frame_concrete = geo.total_area * pv("frame_concrete_per_area", 0.3)
    total_concrete = fnd_concrete + frame_concrete
    add("foundation_concrete", "Бетон фундамента", "м³", fnd_concrete,
        f"{geo.build_area:.0f} м² × {pv('foundation_concrete_per_area', 0.5):g} м³/м²",
        "foundation_concrete_per_area")
    add("frame_concrete", "Бетон монолитного каркаса", "м³", frame_concrete,
        f"{geo.total_area:.0f} м² × {pv('frame_concrete_per_area', 0.3):g} м³/м²",
        "frame_concrete_per_area")
    rebar_t = total_concrete * pv("rebar_kg_per_m3", 100.0) / 1000.0
    add("rebar", "Арматура", "т", rebar_t,
        f"{total_concrete:.0f} м³ × {pv('rebar_kg_per_m3', 100.0):g} кг/м³ ÷ 1000",
        "rebar_kg_per_m3")
    formwork = total_concrete * pv("formwork_m2_per_m3", 2.5)
    add("formwork", "Опалубка", "м²", formwork,
        f"{total_concrete:.0f} м³ × {pv('formwork_m2_per_m3', 2.5):g} м²/м³",
        "formwork_m2_per_m3")

    # ── Перегородки ──
    partitions_m2 = geo.total_area * pv("partition_m2_per_area", 0.6)
    add("partitions", "Перегородки (кладка)", "м²", partitions_m2,
        f"{geo.total_area:.0f} м² × {pv('partition_m2_per_area', 0.6):g} м²/м²",
        "partition_m2_per_area")

    # ── Гидро/теплоизоляция ──
    add("waterproofing_foundation", "Гидроизоляция фундамента", "м²", geo.build_area,
        f"= площадь застройки {geo.build_area:.0f} м²", None)
    add("insulation_foundation", "Теплоизоляция фундамента", "м²", geo.build_area,
        f"= площадь застройки {geo.build_area:.0f} м²", "wall_insulation_thickness_m")
    add("insulation_walls", "Теплоизоляция наружных стен", "м²", geo.facade_area,
        f"= площадь фасада {geo.facade_area:.0f} м²", "wall_insulation_thickness_m")
    add("insulation_roof", "Теплоизоляция кровли", "м²", geo.build_area,
        f"= площадь застройки {geo.build_area:.0f} м²", "roof_insulation_thickness_m")

    # ── Кровля, фасад, остекление ──
    add("roof", "Кровля", "м²", geo.build_area,
        f"= площадь застройки {geo.build_area:.0f} м²", None)
    glazing = geo.facade_area * pv("glazing_share_of_facade", 0.22)
    add("facade", "Фасадные работы", "м²", max(geo.facade_area - glazing, 0.0),
        f"фасад {geo.facade_area:.0f} − остекление {glazing:.0f}", None)
    add("glazing", "Окна, витражи, наружные двери", "м²", glazing,
        f"{geo.facade_area:.0f} м² × {pv('glazing_share_of_facade', 0.22):g}",
        "glazing_share_of_facade")

    # ── Отделка (по классу) ──
    fin = pv("finishing_factor", 1.0)
    screed = geo.total_area * fin
    wall_plaster = (geo.facade_area + partitions_m2 * 2.0) * fin
    ceiling = geo.total_area * fin
    add("screed", "Стяжка полов", "м²", screed,
        f"{geo.total_area:.0f} м² × коэф. отделки {fin:g}", "finishing_factor")
    add("wall_finish", "Штукатурка/шпатлёвка стен", "м²", wall_plaster,
        f"(фасад {geo.facade_area:.0f} + 2×перегородки {partitions_m2:.0f}) × {fin:g}",
        "finishing_factor")
    add("ceiling_finish", "Отделка потолков", "м²", ceiling,
        f"{geo.total_area:.0f} м² × коэф. отделки {fin:g}", "finishing_factor")

    # ── Инженерные системы (по классу инженерии) ──
    eng = pv("engineering_factor", 1.0)
    eng_qty = geo.total_area * eng
    for key, title in (
        ("hvac", "Внутренние сети ОВиК"),
        ("plumbing", "Водоснабжение и канализация"),
        ("electrical", "Электромонтажные работы"),
        ("low_current", "Слаботочные системы"),
    ):
        add(key, title, "м²", eng_qty,
            f"{geo.total_area:.0f} м² × коэф. инженерии {eng:g}", "engineering_factor")

    # ── Благоустройство ──
    add("landscaping", "Благоустройство и наружные сети", "м²", geo.total_area,
        f"= общая площадь {geo.total_area:.0f} м²", None)

    return out
