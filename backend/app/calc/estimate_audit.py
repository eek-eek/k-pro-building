"""Аудит готовой сметы («резервный провайдер проверяет»).

Три кейса:
  1. Цена — отклонение цены строки от эталона (свежий пересчёт по нормам/каталогу).
  2. Полнота — логические пропуски (карта зависимостей + резервный LLM-провайдер).
  3. Объём — расхождение объёма строки с нормой (свежий пересчёт по площади × норма).

Кейсы 1 и 3 детерминированы (без ИИ): сравниваем сохранённую смету со свежим
пересчётом того же ввода. Кейс 2 — правила + резервный провайдер, мягкая деградация."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..schemas import AuditFinding, AuditReport, BuildingInput, EstimateResult

# Порог отклонения для находки и градация риска.
DEV_MIN = 0.08          # <8% — шум, не сообщаем
DEV_MED = 0.15          # средний риск
DEV_HIGH = 0.30         # высокий риск

# Карта зависимостей: код-триггер присутствует → код-компаньон обязан быть.
DEPENDENCY_RULES: list[tuple[str, str, str]] = [
    ("aerated_block", "masonry_glue", "Есть кладка из газоблока, но нет кладочного раствора/клея"),
    ("concrete_b25", "rebar_a500", "Есть монолитный бетон, но не заложена арматура"),
    ("concrete_b25", "form_panel", "Есть монолитный бетон, но нет опалубки"),
    ("roof_membrane", "primer_roof", "Есть наплавляемая кровля, но нет праймера под неё"),
    ("xps", "xps_fix", "Есть плитный утеплитель, но нет крепежа/клея к нему"),
]


def _severity(dev: float) -> str:
    if dev >= DEV_HIGH:
        return "высокий"
    if dev >= DEV_MED:
        return "средний"
    return "низкий"


def _unit_cost(ln) -> float:
    return ln.material_price + ln.labor_price + ln.machine_price


def _deterministic(stored: EstimateResult, fresh: EstimateResult) -> list[AuditFinding]:
    """Кейсы 1 (цена) и 3 (объём): сохранённое vs свежий пересчёт, по строкам."""
    findings: list[AuditFinding] = []
    fresh_by_title = {ln.title: ln for ln in fresh.lines}
    for ln in stored.lines:
        f = fresh_by_title.get(ln.title)
        if f is None:
            continue
        # Кейс 3 — объём против нормы
        if f.quantity:
            dv = abs(ln.quantity - f.quantity) / f.quantity
            if dv >= DEV_MIN:
                findings.append(AuditFinding(
                    case="volume", severity=_severity(dv),
                    title=f"«{ln.title}»: объём отклоняется от нормы на {dv * 100:.0f}%",
                    detail=(f"в смете {ln.quantity:g} {ln.unit}, по норме "
                            f"(площадь × норма конструктива) ожидается ~{f.quantity:g} {ln.unit}"),
                    recommendation="Проверьте объём: пересчитать по площади и норме расхода конструктива."))
        # Кейс 1 — цена против эталона
        su, fu = _unit_cost(ln), _unit_cost(f)
        if fu:
            dp = abs(su - fu) / fu
            if dp >= DEV_MIN:
                direction = "завышена" if su > fu else "занижена"
                findings.append(AuditFinding(
                    case="price", severity=_severity(dp),
                    title=f"«{ln.title}»: цена {direction} на {dp * 100:.0f}% против эталона",
                    detail=(f"в смете {su:.0f} ₸/{ln.unit}, по каталогу/нормам "
                            f"~{fu:.0f} ₸/{ln.unit}"),
                    recommendation="Сверьте цену с эталоном (Справочник цен / SADI) или обоснуйте отклонение."))
    return findings


def _dependency_gaps(stored: EstimateResult) -> list[AuditFinding]:
    """Кейс 2 (правила): триггер есть в составе, а обязательный компаньон — нет."""
    codes = {r.code for ln in stored.lines for r in (ln.resources or [])}
    out: list[AuditFinding] = []
    for trigger, required, msg in DEPENDENCY_RULES:
        if trigger in codes and required not in codes:
            out.append(AuditFinding(
                case="completeness", severity="высокий",
                title="Возможный пропуск позиции", detail=msg,
                recommendation="Добавьте недостающую позицию или подтвердите, что она не нужна."))
    return out


_LLM_CASES = {"пропуск", "лишнее", "объём", "пропорция", "цена", "несоответствие",
              "противоречие", "норма", "прочее"}


def _llm_review(db: Session, inp: BuildingInput, stored: EstimateResult
                ) -> tuple[list[AuditFinding], bool, str, str]:
    """Кейс 2 (ИИ): резервный провайдер рассуждением ищет ЛЮБЫЕ расхождения —
    не только пропуски: лишнее/нелогичное, несоответствие типу объекта, подозрительные
    объёмы и пропорции, ценовые аномалии, внутренние противоречия.
    Возвращает (находки, запускался, имя_провайдера, заметка-о-деградации)."""
    from ..settings_service import get_effective_settings
    from ..llm.factory import build_named_provider
    from ..llm.base import LLMUnavailable

    eff = get_effective_settings(db)
    name = eff.cross_check_provider or ""
    if not name:
        return [], False, "", "резервный провайдер не задан в Настройках"
    verifier = build_named_provider(eff, name)
    if not getattr(verifier, "available", False):
        return [], False, name, "резервный провайдер недоступен (нет ключа)"

    # Богатый контекст: по каждой строке — объём, удельная цена, сумма и состав.
    lines_ctx = []
    for ln in stored.lines:
        mats = [r.name for r in (ln.resources or []) if r.kind == "material"][:5]
        uc = ln.material_price + ln.labor_price + ln.machine_price
        lines_ctx.append(
            f"{ln.section} / {ln.title}: {ln.quantity:g} {ln.unit} × {uc:.0f} ₸ = {ln.total:.0f} ₸"
            + (f"; материалы: {', '.join(mats)}" if mats else ""))
    t = stored.totals
    system = (
        "Ты — опытный сметчик-контролёр РК. Тщательно, с рассуждением, проверь предварительную "
        "смету и найди ЛЮБЫЕ расхождения и проблемы, а не только пропуски. Ищи: (1) пропущенные "
        "работы/материалы; (2) лишние или нелогичные для такого объекта позиции; (3) несоответствие "
        "типу объекта/этажности/площади; (4) подозрительные объёмы и ПРОПОРЦИИ (например арматура "
        "относительно бетона, площадь кровли/фасада относительно застройки, толщина/расход); "
        "(5) ценовые аномалии (позиция дороже/дешевле разумного); (6) внутренние противоречия. "
        "ВАЖНО: позиции укрупнённые — то, что указано в составе строки, уже учтено, не считай это "
        "пропуском. Не придирайся к мелочам; только существенное, с числовым обоснованием где можно. "
        "Верни СТРОГО JSON: {\"findings\":[{\"category\":\"пропуск|лишнее|объём|пропорция|цена|"
        "несоответствие|противоречие|норма|прочее\",\"issue\":\"кратко суть\",\"reason\":\"почему, "
        "с числами\",\"severity\":\"низкий|средний|высокий\",\"recommendation\":\"что сделать\"}]}. "
        "Если проблем нет — {\"findings\":[]}."
    )
    user = (
        f"Объект: {inp.object_type}, г. {inp.city}, этажей {inp.floors}, "
        f"габарит {inp.building_length:g}×{inp.building_width:g} м, общая площадь {inp.total_area:g} м². "
        f"Итоги: прямые {t.direct:.0f} ₸, всего с НДС {t.grand_total:.0f} ₸.\n"
        f"Строки сметы (раздел / позиция: объём × удельная цена = сумма; состав):\n- "
        + "\n- ".join(lines_ctx)
    )
    try:
        data, _ = verifier.extract_json(system, user, use_search=False)
    except LLMUnavailable:
        return [], False, name, "ошибка вызова резервного провайдера"
    except Exception:
        return [], False, name, "резервный провайдер вернул ошибку"

    out: list[AuditFinding] = []
    for m in (data.get("findings") or [])[:15]:
        issue = str(m.get("issue", "")).strip()
        if not issue:
            continue
        sev = str(m.get("severity", "средний")).strip().lower()
        if sev not in {"низкий", "средний", "высокий"}:
            sev = "средний"
        cat = str(m.get("category", "прочее")).strip().lower()
        if cat not in _LLM_CASES:
            cat = "прочее"
        out.append(AuditFinding(
            case=cat, severity=sev, title=issue,
            detail=str(m.get("reason", "")).strip(),
            recommendation=str(m.get("recommendation", "")).strip()
            or "Проверьте позицию и при подтверждении скорректируйте."))
    return out, True, name, ""


_ORDER = {"высокий": 0, "средний": 1, "низкий": 2}


def audit_estimate(db: Session, est) -> AuditReport:
    """Полный аудит текущей версии сметы. Смету не изменяет."""
    from ..norms import resolve_norm_profile
    from .estimate import build_estimate

    cv = est.current_version
    stored = EstimateResult(**cv.result)
    inp = BuildingInput(**cv.input)

    findings: list[AuditFinding] = []
    # Кейсы 1 и 3 — детерминированно против свежего пересчёта.
    try:
        profile = resolve_norm_profile(db, inp)
        fresh = build_estimate(db, inp, profile)
        findings += _deterministic(stored, fresh)
    except Exception:
        pass  # пересчёт не удался — детерминированную часть пропускаем, аудит не падает
    # Кейс 2 — правила-зависимости (надёжный минимум) + общий аудит рассуждающей моделью.
    findings += _dependency_gaps(stored)
    llm_findings, llm_used, llm_provider, note = _llm_review(db, inp, stored)
    findings += llm_findings

    findings.sort(key=lambda f: _ORDER.get(f.severity, 3))
    high = sum(1 for f in findings if f.severity == "высокий")
    if not findings:
        summary = "Аудит не выявил существенных отклонений."
    else:
        summary = f"Найдено замечаний: {len(findings)} (высокий риск: {high})."
    return AuditReport(
        findings=findings, checked_lines=len(stored.lines),
        llm_used=llm_used, llm_provider=llm_provider, note=note, summary=summary,
    )
