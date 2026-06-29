"""Пер-ресурсная свежесть/индексация цен строки сметы."""
import datetime as dt

from app.calc.estimate import _inflate_resources, _price_age_months, PRICE_STALE_MONTHS
from app.schemas import ResourceLine

_TODAY = dt.date(2026, 6, 1)


def _res(source, date, price=100):
    return ResourceLine(code="x", name="X", kind="material", unit="м³",
                        consumption=1, price=price, source=source, updated_at=date)


def test_age_months_is_day_aware():
    assert _price_age_months("2026-05-01", _TODAY) == 1
    assert _price_age_months("2026-05-15", _TODAY) == 0   # неполный последний месяц
    assert _price_age_months("", _TODAY) is None
    assert _price_age_months("мусор", _TODAY) is None


def test_fresh_resource_not_stale_not_inflated():
    res = [_res("ssc", "2026-05-01")]
    src, date, stale, infl = _inflate_resources(res, _TODAY, 12.0)
    assert not stale and not infl and res[0].price == 100
    assert src == "ssc" and date == "2026-05-01"


def test_stale_resource_inflated():
    res = [_res("erer", "2025-06-01")]  # 12 мес
    _src, _date, stale, infl = _inflate_resources(res, _TODAY, 12.0)
    assert stale and infl and res[0].price > 100


def test_stale_without_inflation_flags_only():
    res = [_res("erer", "2025-06-01")]
    _src, _date, stale, infl = _inflate_resources(res, _TODAY, 0.0)
    assert stale and not infl and res[0].price == 100


def test_fresh_does_not_mask_stale_resource():
    res = [_res("ssc", "2026-05-01", 100), _res("erer", "2024-06-01", 200)]  # свежий + старый
    src, date, stale, infl = _inflate_resources(res, _TODAY, 10.0)
    assert stale and infl
    assert res[0].price == 100           # свежий ресурс не тронут
    assert res[1].price > 200            # старый ресурс проиндексирован
    assert date == "2026-05-01" and src == "ssc"  # дата+источник самой свежей цены


def test_older_resource_inflated_more():
    r12 = [_res("e", "2025-06-01", 100)]   # 12 мес
    r24 = [_res("e", "2024-06-01", 100)]   # 24 мес
    _inflate_resources(r12, _TODAY, 10.0)
    _inflate_resources(r24, _TODAY, 10.0)
    assert r24[0].price > r12[0].price and PRICE_STALE_MONTHS == 6
