"""Сборка сметы: объёмы × цены → строки, разделы, итоги (накладные/резерв/НДС)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from ..schemas import (
    BuildingInput,
    EstimateLine,
    EstimateResult,
    EstimateTotals,
    NormProfile,
)
from .generalized import compute_cost_anchor
from .geometry import derive
from .pricing import get_price
from .resource_catalog import db_snapshot_for, rollup
from .volumes import compute_volumes

# (номер, название раздела, [ключи объёмов], [подстроки для фильтра по видам работ])
SECTIONS: list[tuple[int, str, list[str], list[str]]] = [
    (2, "Земляные работы и вывоз грунта",
     ["excavation", "soil_removal", "backfill"], ["земл", "грунт"]),
    (3, "Фундаменты и монолитные ЖБ конструкции",
     ["foundation_concrete", "frame_concrete", "rebar", "formwork"],
     ["фундамент", "монолит", "армир", "бетон"]),
    (4, "Кладка наружных/внутренних стен и перегородок",
     ["partitions"], ["кладк", "перегород"]),
    (5, "Гидроизоляция и теплоизоляция",
     ["waterproofing_foundation", "insulation_foundation",
      "insulation_walls", "insulation_roof"], ["гидроизоляц", "теплоизоляц", "изоляц"]),
    (6, "Кровля", ["roof"], ["кровл"]),
    (7, "Фасадные работы", ["facade"], ["фасад"]),
    (8, "Окна, витражи, наружные двери", ["glazing"], ["окн", "витраж", "двер"]),
    (9, "Черновая и чистовая отделка",
     ["screed", "wall_finish", "ceiling_finish"], ["отделк", "штукатур"]),
    (10, "Внутренние сети ОВиК", ["hvac"], ["овик", "отоплен", "вентиляц"]),
    (11, "Водоснабжение и канализация", ["plumbing"], ["водоснаб", "канализ"]),
    (12, "Электромонтажные работы", ["electrical"], ["электр"]),
    (13, "Слаботочные системы", ["low_current"], ["слаботоч"]),
    (14, "Благоустройство и наружные сети",
     ["landscaping"], ["благоустр"]),
]

PREP_TITLE = "Подготовительные работы и временные сооружения"

CONTRACTOR_QUESTIONS = [
    "На основании каких нормативных документов и сборников расценок составлена смета "
    "(СН РК, РДС РК, собственные нормативы)?",
    "Какие укрупнённые показатели использованы для объёмов бетона, арматуры, опалубки? "
    "Предоставьте расчёты.",
    "Стоимость 1 м³ бетона с доставкой и укладкой, марка бетона?",
    "Стоимость 1 т арматуры с заготовкой и монтажом, класс арматуры?",
    "Конкретные марки и производители ключевых материалов (бетон, утеплитель, фасад, окна)?",
    "Структура прямых затрат (материалы / труд / машины) по основным разделам?",
    "Процент накладных расходов и сметной прибыли?",
    "Учтены ли временные здания и сооружения, геодезия, лабораторные испытания, охрана труда?",
    "Предусмотрен ли резерв на непредвиденные работы и в каком размере?",
    "Сроки по разделам и общий срок строительства, гарантии, график оплаты?",
]


def _section_included(section_match: list[str], works_lc: list[str]) -> bool:
    if not works_lc:
        return True
    for work in works_lc:
        if any(sub in work for sub in section_match):
            return True
    return False


def build_estimate(
    db: Session, inp: BuildingInput, profile: NormProfile
) -> EstimateResult:
    geo = derive(inp)
    volumes = compute_volumes(inp, profile, geo)
    region = inp.city.split("/")[0].strip() or "KZ"

    works_lc = [w.lower() for w in inp.works if w.strip()]
    lines: list[EstimateLine] = []
    section_totals: dict[str, float] = {}
    direct_core = 0.0

    for number, title, keys, match in SECTIONS:
        if not _section_included(match, works_lc):
            continue
        sub_index = 0
        section_sum = 0.0
        for key in keys:
            vol = volumes.get(key)
            if vol is None or vol.quantity <= 0:
                continue
            resources = db_snapshot_for(db, key, region)
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
        if section_sum > 0:
            section_totals[title] = round(section_sum)
            direct_core += section_sum

    # Раздел 1: подготовительные работы — 1.5% от прямых затрат (укрупнённо)
    prep_title = "Подготовительные работы и временные сооружения"
    if not works_lc or any("подготов" in w or "временны" in w for w in works_lc):
        prep_total = round(direct_core * 0.015)
        if prep_total > 0:
            lines.insert(
                0,
                EstimateLine(
                    no="1.1",
                    section=prep_title,
                    title="Подготовительные работы и временные сооружения",
                    norm="СН РК 8.02-04-2002 (аналог)",
                    unit="усл.",
                    quantity=1,
                    labor_price=prep_total,
                    total=prep_total,
                    comment="1.5% от прямых затрат (ориентировочно)",
                ),
            )
            section_totals[prep_title] = prep_total
            direct_core += prep_total

    direct = round(direct_core)
    overhead = round(direct * inp.overhead_pct / 100)
    subtotal1 = direct + overhead
    contingency = round(subtotal1 * inp.contingency_pct / 100)
    subtotal2 = subtotal1 + contingency
    vat = round(subtotal2 * inp.vat_pct / 100)
    grand = subtotal2 + vat

    totals = EstimateTotals(
        direct=direct,
        overhead=overhead,
        overhead_pct=inp.overhead_pct,
        subtotal_with_overhead=subtotal1,
        contingency=contingency,
        contingency_pct=inp.contingency_pct,
        subtotal_with_contingency=subtotal2,
        vat=vat,
        vat_pct=inp.vat_pct,
        grand_total=grand,
    )

    review_count = sum(1 for ln in lines if ln.needs_review)
    warnings = [
        "Смета предварительная (ориентировочная), низкий класс точности (класс 5): "
        "без рабочих чертежей и спецификаций.",
        "Цены индикативные, рыночные на текущую дату по региону, требуют уточнения "
        "у поставщиков и подрядчиков.",
        "Не является основанием для договоров подряда — только для предварительной "
        "оценки и сравнения предложений.",
    ]
    if review_count:
        warnings.append(
            f"Позиций, требующих проверки сметчиком: {review_count}. "
            "Номера норм не выдуманы; неподтверждённые отмечены."
        )
    if profile.from_cache:
        warnings.append("Нормативный профиль взят из кэша БД (без обращения к LLM).")
    if profile.cross_check and profile.cross_check.ran:
        cc = profile.cross_check
        msg = (f"Профиль прошёл кросс-проверку ({cc.verifier}): "
               f"подтверждено {cc.agreed}, расхождений {cc.disputed}")
        if cc.missing:
            msg += f", без ответа {cc.missing}"
        if cc.extra_keys:
            msg += f"; вторая модель дополнительно предложила: {', '.join(cc.extra_keys)}"
        warnings.append(msg + ".")
    elif (profile.cross_check and profile.cross_check.enabled
          and not profile.cross_check.ran and profile.cross_check.reason):
        warnings.append(f"Кросс-проверка включена, но не выполнена: {profile.cross_check.reason}.")

    # Укрупнённый ориентир РК (НДЦС/УСН) — сверка ресурсной сметы; не меняет итоги.
    cost_anchor = compute_cost_anchor(db, inp, totals.grand_total)
    if cost_anchor is not None and abs(cost_anchor.deviation_pct) > 25:
        warnings.append(
            f"Ресурсная смета отклоняется от укрупнённого ориентира РК на "
            f"{cost_anchor.deviation_pct:+.0f}% (укрупнённо ≈ {cost_anchor.value:,.0f} ₸"
            + ("; предварительный показатель" if cost_anchor.provisional else "") + ")."
        )

    clarifications = [
        "Полный комплект проектной документации (АР, КР, ОВиК, ВК, ЭОМ, СС).",
        "Толщина и армирование фундаментной плиты; толщины перекрытий, сечения колонн/стен.",
        "Конкретные марки материалов (фасад, кровля, окна, утеплитель, инженерия).",
        "Условия подключения к городским сетям (вода, канализация, электричество, тепло).",
        "Состав благоустройства и наружных сетей; состав временных зданий и сооружений.",
    ]
    for p in profile.params.values():
        if p.needs_review and p.note:
            clarifications.append(f"Проверить: {p.category} — {p.note}")

    return EstimateResult(
        project_name=inp.project_name,
        city=inp.city,
        object_type=inp.object_type,
        warnings=warnings,
        sources=profile.sources,
        volumes=list(volumes.values()),
        lines=lines,
        section_totals=section_totals,
        totals=totals,
        cost_anchor=cost_anchor,
        contractor_questions=CONTRACTOR_QUESTIONS,
        clarifications=clarifications,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    )


def recompute_estimate(
    prev: EstimateResult, lines: list[EstimateLine], inp: BuildingInput
) -> EstimateResult:
    """Пересчитать все суммы из `lines` (сервер — единственный источник истины),
    сохранив неценовой контекст из `prev`. Округление повторяет build_estimate.
    Внимание: изменяет переданные объекты строк на месте — передавайте копии,
    если нужны исходные."""
    core = [ln for ln in lines if ln.no != "1.1" and ln.section != PREP_TITLE]
    prep_existing = [ln for ln in lines if ln.no == "1.1" or ln.section == PREP_TITLE]

    section_totals: dict[str, float] = {}
    direct_core = 0.0
    rebuilt: list[EstimateLine] = []
    for ln in core:
        if ln.resources:
            ln.material_price, ln.labor_price, ln.machine_price = rollup(ln.resources)
        unit_cost = ln.material_price + ln.labor_price + ln.machine_price
        ln.total = round(ln.quantity * unit_cost)
        rebuilt.append(ln)
        if ln.total == 0:
            continue
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
            prep.norm = "СН РК 8.02-04-2002 (аналог)"
            prep.comment = "1.5% от прямых затрат (ориентировочно)"
            prep.needs_review = False
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
    # перенести укрупнённый якорь, пересчитав отклонение от нового итога
    anchor = prev.cost_anchor
    if anchor is not None:
        anchor = anchor.model_copy(update={
            "resource_grand": round(grand),
            "deviation_pct": round((grand - anchor.value) / anchor.value * 100, 1)
                              if anchor.value else 0.0,
        })
    return EstimateResult(
        project_name=prev.project_name, city=prev.city, object_type=prev.object_type,
        precision_class=prev.precision_class, warnings=prev.warnings,
        sources=prev.sources, volumes=prev.volumes, lines=final_lines,
        cost_anchor=anchor,
        section_totals=section_totals, totals=totals,
        contractor_questions=prev.contractor_questions,
        clarifications=prev.clarifications,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        llm_narrative=prev.llm_narrative,
    )
