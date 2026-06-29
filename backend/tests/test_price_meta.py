"""Источник/дата/свежесть цен строки + индексация на инфляцию."""
import datetime as dt

from app.calc.estimate import _line_price_meta, PRICE_STALE_MONTHS
from app.schemas import ResourceLine

_TODAY = dt.date(2026, 6, 1)


def _res(source, date):
    return ResourceLine(code="x", name="X", kind="material", unit="м³",
                        consumption=1, price=100, source=source, updated_at=date)


def test_fresh_prices_not_stale():
    src, date, stale, factor = _line_price_meta([_res("ssc", "2026-05-01")], _TODAY, 12.0)
    assert not stale and factor == 1.0
    assert src == "ssc" and date == "2026-05-01"


def test_stale_prices_flagged_without_inflation():
    src, date, stale, factor = _line_price_meta([_res("erer", "2025-06-01")], _TODAY, 0.0)
    assert stale and factor == 1.0  # ≥6 мес, но инфляция выключена → множитель 1


def test_stale_prices_indexed_by_inflation():
    src, date, stale, factor = _line_price_meta([_res("erer", "2025-06-01")], _TODAY, 12.0)
    assert stale and factor > 1.0  # 12 мес × 12%/год ≈ 1.12


def test_no_date_means_not_stale():
    src, date, stale, factor = _line_price_meta([_res("seed", "")], _TODAY, 12.0)
    assert not stale and factor == 1.0 and date == ""


def test_dominant_source_and_latest_date():
    res = [_res("ssc", "2026-01-01"), _res("ssc", "2026-02-01"), _res("erer", "2026-03-01")]
    src, date, stale, factor = _line_price_meta(res, _TODAY, 0.0)
    assert src == "ssc" and date == "2026-03-01"


def test_threshold_is_six_months():
    assert PRICE_STALE_MONTHS == 6
    # ровно на пороге (6 мес) — уже несвежо
    _, _, stale, _ = _line_price_meta([_res("ssc", "2025-12-01")], _TODAY, 0.0)
    assert stale
