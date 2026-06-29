"""Детализация конструктивов: сплиты ОВиК/ВК/благоустройство + доп. конструктивы."""
from app.calc import build_estimate
from app.norms import resolve_norm_profile
from app.schemas import BuildingInput


def _calc(db, **kw):
    inp = BuildingInput(demo_mode=True, use_search=False, **kw)
    return inp, build_estimate(db, inp, resolve_norm_profile(db, inp))


def test_hvac_split_into_three(db):
    _, r = _calc(db, object_type="Жилой дом", total_area=1500, floors=10)
    titles = [l.title for l in r.lines]
    assert {"Отопление", "Вентиляция", "Кондиционирование"} <= set(titles)


def test_plumbing_and_landscaping_split(db):
    _, r = _calc(db, object_type="Жилой дом", total_area=1500, floors=10)
    titles = set(l.title for l in r.lines)
    assert {"Водопровод (ХВС/ГВС)", "Канализация"} <= titles
    assert {"Благоустройство территории", "Наружные инженерные сети"} <= titles


def test_split_sublines_flagged_for_review(db):
    _, r = _calc(db, object_type="Жилой дом", total_area=1500, floors=10)
    heating = next(l for l in r.lines if l.title == "Отопление")
    assert heating.needs_review and "разбивк" in heating.comment


def test_additional_constructs_offered_as_recommendations(db):
    # «Дополнительно» (Двери/Чистовая/Прочие) — опциональные рекомендации, не авто-строки
    from app.calc import applicable_recommendations
    inp, r = _calc(db, object_type="Жилой дом", total_area=1500, floors=10)
    keys = {rec["key"] for rec in applicable_recommendations(inp, r)}
    assert {"doors", "fine_finish", "misc_works"} <= keys
    # и не добавлены автоматически в смету
    assert "Внутренние двери" not in [l.title for l in r.lines]
