from app.schemas import EstimateLine, ResourceLine


def test_estimate_line_defaults_to_no_resources():
    ln = EstimateLine(no="3.1", section="Фундаменты", title="Бетон",
                      unit="м³", quantity=10)
    assert ln.resources == []


def test_resource_line_roundtrips_through_estimate_line():
    r = ResourceLine(code="concrete_b25", name="Бетон B25",
                     kind="material", unit="м³", consumption=1.02, price=30000)
    ln = EstimateLine(no="3.1", section="Фундаменты", title="Бетон",
                      unit="м³", quantity=10, resources=[r])
    dumped = ln.model_dump()
    restored = EstimateLine(**dumped)
    assert restored.resources[0].code == "concrete_b25"
    assert restored.resources[0].consumption == 1.02
    assert restored.resources[0].kind == "material"


from app.calc import build_estimate, rollup
from app.calc.estimate import recompute_estimate  # noqa: F401 (used by later tests)
from app.norms.resolver import resolve_norm_profile
from app.database import SessionLocal
from app.schemas import BuildingInput
from app.seed import run_seed


def _build():
    run_seed()
    db = SessionLocal()
    try:
        inp = BuildingInput(object_type="Жилой дом", demo_mode=True, use_search=False)
        profile = resolve_norm_profile(db, inp)
        return inp, build_estimate(db, inp, profile)
    finally:
        db.close()


def test_concrete_line_has_resources_and_price_from_rollup():
    _, res = _build()
    line = next(l for l in res.lines if l.title == "Бетон фундамента")
    assert line.resources, "у строки бетона должен быть ресурсный состав"
    material, labor, machine = rollup(line.resources)
    assert line.material_price == material
    assert line.labor_price == labor
    assert line.machine_price == machine
    assert line.total == round(line.quantity * (material + labor + machine))


def test_line_without_composition_has_no_resources():
    _, res = _build()
    line = next(l for l in res.lines if l.title == "Кровля")
    assert line.resources == []
    assert line.total > 0


def test_recompute_is_noop_with_resources():
    inp, res = _build()
    lines = [l.model_copy(deep=True) for l in res.lines]
    out = recompute_estimate(res, lines, inp)
    assert [round(l.total) for l in out.lines] == [round(l.total) for l in res.lines]
    assert out.totals.grand_total == res.totals.grand_total


def test_editing_resource_consumption_changes_line_and_grand_total():
    inp, res = _build()
    lines = [l.model_copy(deep=True) for l in res.lines]
    line = next(l for l in lines if l.title == "Бетон фундамента")
    old_material_price = line.material_price  # capture BEFORE recompute (it mutates in place)
    conc = next(r for r in line.resources if r.code == "concrete_b25")
    conc.consumption = conc.consumption * 2
    out = recompute_estimate(res, lines, inp)
    out_line = next(l for l in out.lines if l.title == "Бетон фундамента")
    exp_m = sum(r.consumption * r.price for r in out_line.resources if r.kind == "material")
    assert out_line.material_price == exp_m
    assert out_line.material_price > old_material_price
    assert out.totals.grand_total > res.totals.grand_total


def test_editing_resource_price_changes_total():
    inp, res = _build()
    lines = [l.model_copy(deep=True) for l in res.lines]
    line = next(l for l in lines if l.title == "Арматура")
    steel = next(r for r in line.resources if r.code == "rebar_a500")
    steel.price = steel.price + 100000
    out = recompute_estimate(res, lines, inp)
    out_line = next(l for l in out.lines if l.title == "Арматура")
    exp_m = sum(r.consumption * r.price for r in out_line.resources if r.kind == "material")
    assert out_line.material_price == exp_m
    assert out.totals.grand_total > res.totals.grand_total


def test_changing_work_quantity_scales_line_total_from_resources():
    inp, res = _build()
    lines = [l.model_copy(deep=True) for l in res.lines]
    line = next(l for l in lines if l.title == "Бетон фундамента")
    unit_cost = line.material_price + line.labor_price + line.machine_price
    line.quantity = line.quantity + 5
    out = recompute_estimate(res, lines, inp)
    out_line = next(l for l in out.lines if l.title == "Бетон фундамента")
    assert out_line.total == round(out_line.quantity * unit_cost)
