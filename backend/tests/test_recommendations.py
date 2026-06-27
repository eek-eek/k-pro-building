from app.calc import (
    build_estimate,
    recompute_estimate,
    applicable_recommendations,
    build_recommendation_line,
    REC_SECTION,
)
from app.calc.recommendations import _BY_KEY
from app.norms.resolver import resolve_norm_profile
from app.schemas import BuildingInput
from app.database import SessionLocal
from app.seed import run_seed


def _result(**kw):
    run_seed()
    db = SessionLocal()
    try:
        inp = BuildingInput(object_type="Жилой дом", demo_mode=True, use_search=False, **kw)
        profile = resolve_norm_profile(db, inp)
        return inp, build_estimate(db, inp, profile)
    finally:
        db.close()


def test_applicable_recs_have_nonzero_computed_cost():
    inp, res = _result()
    recs = applicable_recommendations(inp, res)
    assert recs, "должны быть хоть какие-то рекомендации"
    assert all(r["estimated_total"] > 0 for r in recs)
    assert all(r["quantity"] > 0 for r in recs)
    # estimated_total согласован с объёмом и ценами (та же формула, что в смете)
    for r in recs:
        assert r["estimated_total"] == round(
            r["quantity"] * (r["material_price"] + r["labor_price"] + r["machine_price"])
        )


def test_pct_of_direct_recommendation_matches_basis():
    inp, res = _result()
    recs = {r["key"]: r for r in applicable_recommendations(inp, res)}
    # «Авторский и технический надзор» = 1.5% от прямых затрат
    assert "supervision" in recs
    assert recs["supervision"]["estimated_total"] == round(res.totals.direct * 0.015)


def test_build_line_is_fully_filled_and_self_consistent():
    inp, res = _result()
    line = build_recommendation_line("geodesy", inp, res)
    assert line.no == "15.1"
    assert line.section == REC_SECTION
    assert line.needs_review is True
    assert line.total > 0
    assert line.total == round(
        line.quantity * (line.material_price + line.labor_price + line.machine_price)
    )


def test_adding_recommendation_raises_grand_total_and_recompute_keeps_it():
    inp, res = _result()
    line = build_recommendation_line("supervision", inp, res)
    out = recompute_estimate(res, list(res.lines) + [line], inp)
    assert out.totals.grand_total > res.totals.grand_total
    assert REC_SECTION in out.section_totals
    added = next(l for l in out.lines if l.section == REC_SECTION)
    assert added.total == round(
        added.quantity * (added.material_price + added.labor_price + added.machine_price)
    )
    assert out.section_totals[REC_SECTION] == added.total


def test_added_recommendation_drops_out_of_applicable_list():
    inp, res = _result()
    line = build_recommendation_line("supervision", inp, res)
    out = recompute_estimate(res, list(res.lines) + [line], inp)
    keys = {r["key"] for r in applicable_recommendations(inp, out)}
    assert "supervision" not in keys


def test_second_recommendation_gets_next_number():
    inp, res = _result()
    first = build_recommendation_line("supervision", inp, res)
    out = recompute_estimate(res, list(res.lines) + [first], inp)
    second = build_recommendation_line("geodesy", inp, out)
    assert second.no == "15.2"


def test_floors_min_filters_elevators():
    inp_low, res_low = _result(floors=4)
    keys_low = {r["key"] for r in applicable_recommendations(inp_low, res_low)}
    assert "elevators" not in keys_low

    inp_hi, res_hi = _result(floors=9)
    keys_hi = {r["key"] for r in applicable_recommendations(inp_hi, res_hi)}
    assert "elevators" in keys_hi


def test_unknown_recommendation_key_raises():
    inp, res = _result()
    try:
        build_recommendation_line("does-not-exist", inp, res)
        assert False, "ожидался KeyError"
    except KeyError:
        pass


def test_catalog_keys_are_unique():
    keys = [r.key for r in _BY_KEY.values()]
    assert len(keys) == len(set(keys))
