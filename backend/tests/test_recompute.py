from app.calc import build_estimate, recompute_estimate
from app.norms.resolver import resolve_norm_profile
from app.schemas import BuildingInput
from app.database import SessionLocal
from app.seed import run_seed


def _result():
    run_seed()
    db = SessionLocal()
    try:
        inp = BuildingInput(object_type="Жилой дом", demo_mode=True, use_search=False)
        profile = resolve_norm_profile(db, inp)
        return inp, build_estimate(db, inp, profile)
    finally:
        db.close()


def test_recompute_is_noop_on_unedited_estimate():
    inp, res = _result()
    again = recompute_estimate(res, [l.model_copy(deep=True) for l in res.lines], inp)
    assert [l.total for l in again.lines] == [l.total for l in res.lines]
    assert again.section_totals == res.section_totals
    assert again.totals.model_dump() == res.totals.model_dump()


def test_recompute_overwrites_bogus_line_total():
    inp, res = _result()
    lines = [l.model_copy(deep=True) for l in res.lines]
    target = next(l for l in lines if l.no != "1.1")
    target.total = 999999999
    out = recompute_estimate(res, lines, inp)
    fixed = next(l for l in out.lines if l.no == target.no)
    assert fixed.total == round(
        fixed.quantity * (fixed.material_price + fixed.labor_price + fixed.machine_price)
    )
    assert fixed.total != 999999999


def test_recompute_carries_forward_warnings_and_sources():
    inp, res = _result()
    out = recompute_estimate(res, [l.model_copy(deep=True) for l in res.lines], inp)
    assert out.warnings == res.warnings
    assert out.precision_class == res.precision_class
    assert len(out.volumes) == len(res.volumes)


def test_recompute_zeroed_line_excluded_from_totals():
    inp, res = _result()
    lines = [l.model_copy(deep=True) for l in res.lines]
    target = next(l for l in lines if l.no != "1.1")
    target.quantity = 0
    out = recompute_estimate(res, lines, inp)
    z = next(l for l in out.lines if l.no == target.no)
    assert z.total == 0
    assert out.totals.grand_total < res.totals.grand_total
