from app.calc.resource_catalog import COMPOSITIONS, rollup, snapshot_for
from app.calc.pricing import PRICES, price_key_for


def test_rollup_sums_by_kind():
    res = snapshot_for("foundation_concrete")
    material, labor, machine = rollup(res)
    assert material > 0 and labor > 0 and machine > 0
    exp_m = sum(r.consumption * r.price for r in res if r.kind == "material")
    assert abs(material - exp_m) < 1e-6


def test_rollup_empty_is_zero():
    assert rollup([]) == (0, 0, 0)


def test_snapshot_for_unknown_key_is_empty():
    assert snapshot_for("does_not_exist") == []


def test_snapshot_returns_independent_copies():
    a = snapshot_for("rebar")
    b = snapshot_for("rebar")
    a[0].price = 999999
    assert b[0].price != 999999


def test_compositions_within_sanity_band_of_flat_prices():
    for key in COMPOSITIONS:
        material, labor, machine = rollup(snapshot_for(key))
        composed = material + labor + machine
        flat = PRICES[price_key_for(key)]
        flat_total = flat.material + flat.labor + flat.machine
        assert 0.6 * flat_total <= composed <= 1.4 * flat_total, (
            f"{key}: composed={composed:.0f} flat={flat_total:.0f}"
        )


def test_every_volume_work_has_a_composition():
    from app.calc.volumes import compute_volumes
    from app.norms.resolver import resolve_norm_profile
    from app.schemas import BuildingInput
    from app.database import SessionLocal
    from app.seed import run_seed

    run_seed()
    db = SessionLocal()
    try:
        inp = BuildingInput(object_type="Жилой дом", demo_mode=True, use_search=False)
        profile = resolve_norm_profile(db, inp)
        volumes = compute_volumes(inp, profile)
        missing = [k for k in volumes if k not in COMPOSITIONS]
        assert not missing, f"нет ресурсного состава для: {missing}"
    finally:
        db.close()
