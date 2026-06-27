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
