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
