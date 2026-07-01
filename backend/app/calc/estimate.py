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
from ..settings_service import get_effective_settings
from .geometry import derive
from .labor_tariff import apply_labor_tariffs, region_for_city, worker_rates
from .material_revision import apply_material_revision
from .pricing import get_price
from .resource_catalog import db_snapshot_for, rollup
from .volumes import compute_volumes

PRICE_STALE_MONTHS = 6  # порог «несвежести» цен — обратить внимание сметчику

# (номер, название раздела, [ключи объёмов], [подстроки для фильтра по видам работ])
# Разделы = «конструктивы» (по мапингу сметчика). Каждый объём отнесён к своему
# конструктиву: теплоизоляция стен → Фасадные, теплоизоляция кровли → Кровля,
# стяжка → Полы, штукатурка/потолки → Внутренняя отделка.
SECTIONS: list[tuple[int, str, list[str], list[str]]] = [
    (2, "Земляные работы",
     ["excavation", "soil_removal", "backfill"], ["земл", "грунт"]),
    (3, "Железобетонный каркас здания",
     ["foundation_concrete", "frame_concrete", "rebar", "formwork"],
     ["монолит", "армир", "бетон", "опалубк", "каркас"]),
    (4, "Гидроизоляция и защита фундамента",
     ["waterproofing_foundation", "insulation_foundation"],
     ["гидроизоляц", "защит"]),
    (5, "Стены и перегородки",
     ["partitions"], ["кладк", "перегород"]),
    (6, "Фасадные работы",
     ["facade", "insulation_walls"], ["фасад", "теплоизоляц", "утеплен"]),
    (7, "Кровля",
     ["roof", "insulation_roof"], ["кровл"]),
    (8, "Окна и витражи", ["glazing"], ["окн", "витраж", "двер"]),
    (9, "Полы", ["screed"], ["стяжк", "полов"]),
    (10, "Внутренняя отделка",
     ["wall_finish", "ceiling_finish"], ["отделк", "штукатур", "потолок"]),
    (11, "Отопление, вентиляция и кондиционирование (ОВиК)",
     ["hvac"], ["овик", "отоплен", "вентиляц", "кондицион"]),
    (12, "Водоснабжение и канализация", ["plumbing"], ["водоснаб", "канализ", "водопровод"]),
    (13, "Электромонтажные работы", ["electrical"], ["электр"]),
    (14, "Слаботочные системы", ["low_current"], ["слаботоч"]),
    (15, "Благоустройство и наружные сети",
     ["landscaping"], ["благоустр"]),
]

# Детализация конструктива на под-позиции (доли — ОРИЕНТИРОВОЧНЫЕ, нужна проверка
# сметчиком; запрос тестировщика: ОВиК→3, ВК→2, благоустройство→2).
SPLIT_SPECS: dict[str, list[tuple[str, float]]] = {
    "hvac": [("Отопление", 0.45), ("Вентиляция", 0.30), ("Кондиционирование", 0.25)],
    "plumbing": [("Водопровод (ХВС/ГВС)", 0.55), ("Канализация", 0.45)],
    "landscaping": [("Благоустройство территории", 0.60), ("Наружные инженерные сети", 0.40)],
}

# Допустимые ключи работ (для валидации бенчмарка — иначе «мёртвые» записи).
VALID_WORK_KEYS = frozenset(k for _, _, keys, _ in SECTIONS for k in keys)


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


def _ru_int(x: float) -> str:
    """Целое с пробелами-разделителями разрядов (ru-формат)."""
    return f"{int(round(x)):,}".replace(",", " ")


def _clamp_total_area(inp: BuildingInput, geo) -> str | None:
    """Контроль общей площади: не больше физического максимума
    (площадь застройки × этажность). При превышении — обрезает inp.total_area
    до максимума и возвращает предупреждение. Если габариты не заданы
    (застройка ≤ 0), максимум не определить — площадь не трогаем."""
    if geo.build_area <= 0:
        return None
    max_area = round(geo.build_area * geo.floors)
    if inp.total_area <= max_area:
        return None
    old = inp.total_area
    inp.total_area = float(max_area)
    return (
        f"Общая площадь {_ru_int(old)} м² превышает физический максимум при заданных "
        f"габаритах и этажности: застройка {_ru_int(geo.build_area)} м² × {geo.floors} эт. "
        f"= {_ru_int(max_area)} м². Площадь автоматически уменьшена до {_ru_int(max_area)} м²."
    )


def _price_age_months(date_str: str, today: dt.date):
    """Возраст цены в полных месяцах (с учётом дня месяца). None — нет/битая дата."""
    try:
        d = dt.date.fromisoformat(date_str)
    except (TypeError, ValueError):
        return None
    months = (today.year - d.year) * 12 + (today.month - d.month)
    if today.day < d.day:  # последний месяц ещё не полный
        months -= 1
    return max(0, months)


def _inflate_resources(resources, today: dt.date, inflation_pct: float):
    """Пер-ресурсная индексация устаревших (≥ PRICE_STALE_MONTHS) цен — мутирует res.price
    по числу месяцев именно его даты. Возвращает (источник самой свежей цены, её дата,
    флаг несвежести строки, была ли индексация). Свежий ресурс не маскирует старые."""
    latest_date, latest_source, stale_any, inflated_any = "", "", False, False
    for res in resources:
        if res.updated_at and res.updated_at > latest_date:
            latest_date, latest_source = res.updated_at, res.source
        months = _price_age_months(res.updated_at, today)
        if months is not None and months >= PRICE_STALE_MONTHS:
            stale_any = True
            if inflation_pct > 0 and res.price:
                res.price = round(res.price * (1 + inflation_pct / 100) ** (months / 12))
                inflated_any = True
    return latest_source, latest_date, stale_any, inflated_any


def build_estimate(
    db: Session, inp: BuildingInput, profile: NormProfile
) -> EstimateResult:
    geo = derive(inp)
    if inp.massing:
        # Произвольная форма: площадь — из массинга (истина), контроль не нужен.
        inp.total_area = float(round(geo.total_area))
        area_warning = None
    else:
        area_warning = _clamp_total_area(inp, geo)
        if area_warning:
            geo = derive(inp)  # пересчёт геометрии под скорректированную площадь
    volumes = compute_volumes(inp, profile, geo)
    region = inp.city.split("/")[0].strip() or "KZ"

    eff = get_effective_settings(db)
    inflation_pct = eff.price_inflation_annual_pct
    today = dt.datetime.now(dt.timezone.utc).date()
    today_iso = today.isoformat()
    stale_count = 0
    inflated = False

    # Ставки труда по тарифам SADI (регион+разряд). Одна выборка на регион.
    tariff_region = region_for_city(region) if eff.labor_tariff_enabled else None
    tariff_rates = worker_rates(db, tariff_region) if tariff_region else {}
    tariff_index = eff.labor_tariff_index or 1.0
    tariff_applied = False
    revise_materials = eff.material_revision_enabled
    revision_applied = False

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
            # Ставки труда из тарифов SADI (до инфляции: тариф штампуется «сегодня»,
            # поэтому не индексируется повторно; материалы/машины — как раньше).
            if apply_labor_tariffs(resources, tariff_rates, tariff_index, today_iso):
                tariff_applied = True
            # Ревизия цен материалов по SADI (штамп «сегодня» — инфляция не задваивает).
            if revise_materials and apply_material_revision(resources, today_iso):
                revision_applied = True
            # Пер-ресурсная индексация инфляции (мутирует цены ресурсов до свёртки —
            # переживает пересчёт; свежий ресурс не маскирует устаревшие).
            psource, pdate, pstale, p_inflated = _inflate_resources(resources, today, inflation_pct)
            if pstale:
                stale_count += 1
            comment = "требует проверки сметчиком" if vol.needs_review else ""
            if p_inflated:
                inflated = True
                comment = (comment + "; " if comment else "") + \
                    f"цены проиндексированы на инфляцию (старые от {pdate})"
            if resources:
                material_price, labor_price, machine_price = rollup(resources)
            else:
                price = get_price(db, key, region)
                material_price, labor_price, machine_price = (
                    price.material, price.labor, price.machine
                )
            unit_cost = material_price + labor_price + machine_price
            splits = SPLIT_SPECS.get(key)
            if splits:
                # Детализация конструктива: под-позиции по ориентировочным долям.
                for sub_title, share in splits:
                    sub_qty = round(vol.quantity * share, 2)
                    sub_total = round(sub_qty * unit_cost)
                    if sub_total <= 0:
                        continue
                    sub_index += 1
                    lines.append(EstimateLine(
                        no=f"{number}.{sub_index}", section=title, title=sub_title,
                        norm=vol.norm, unit=vol.unit, quantity=sub_qty,
                        material_price=material_price, labor_price=labor_price,
                        machine_price=machine_price, total=sub_total, needs_review=True,
                        comment=(comment + "; " if comment else "")
                                + "ориентировочная доля разбивки конструктива — уточнить",
                        resources=[], price_source=psource, price_date=pdate, price_stale=pstale))
                    section_sum += sub_total
            else:
                line_total = round(vol.quantity * unit_cost)
                sub_index += 1
                lines.append(EstimateLine(
                    no=f"{number}.{sub_index}", section=title, title=vol.title,
                    norm=vol.norm, unit=vol.unit, quantity=vol.quantity,
                    material_price=material_price, labor_price=labor_price,
                    machine_price=machine_price, total=line_total,
                    needs_review=vol.needs_review, comment=comment, resources=resources,
                    price_source=psource, price_date=pdate, price_stale=pstale))
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
    if area_warning:
        warnings.insert(0, area_warning)
    if tariff_applied:
        idx = f" × индекс {tariff_index:g}" if tariff_index != 1.0 else ""
        warnings.append(
            f"Ставки труда — по сметным тарифам SADI (регион «{tariff_region}», "
            f"ред. 2016{idx}). Отключается в Настройках."
        )
    if revision_applied:
        warnings.append(
            "Цены части материалов ревизированы по каталогу SADI (заниженные подняты "
            "до SADI; без цены в SADI — ×2.41). Отключается в Настройках."
        )
    if review_count:
        warnings.append(
            f"Позиций, требующих проверки сметчиком: {review_count}. "
            "Номера норм не выдуманы; неподтверждённые отмечены."
        )
    if stale_count:
        msg = (f"Цены по {stale_count} позиц. не обновлялись ≥ {PRICE_STALE_MONTHS} мес — "
               "обратить внимание, актуализировать.")
        if inflated:
            msg += f" Устаревшие цены проиндексированы на инфляцию ({inflation_pct:g}%/год)."
        elif inflation_pct <= 0:
            msg += " Коэффициент инфляции в настройках не задан (индексация выключена)."
        warnings.append(msg)
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
    return EstimateResult(
        project_name=prev.project_name, city=prev.city, object_type=prev.object_type,
        precision_class=prev.precision_class, warnings=prev.warnings,
        sources=prev.sources, volumes=prev.volumes, lines=final_lines,
        section_totals=section_totals, totals=totals,
        contractor_questions=prev.contractor_questions,
        clarifications=prev.clarifications,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        llm_narrative=prev.llm_narrative,
    )
