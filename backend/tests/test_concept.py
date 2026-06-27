from app.concept import propose_concept
from app.schemas import BuildingInput


def test_concept_applies_setback_and_typical_floors():
    inp = propose_concept(area_m2=1000.0, length_m=40.0, width_m=25.0,
                          city="Алматы", object_type="Жилой дом")
    assert isinstance(inp, BuildingInput)
    assert inp.building_length == 28.0   # 40 * 0.7
    assert inp.building_width == 17.5    # 25 * 0.7
    assert inp.floors == 9               # типовая для жилого
    assert inp.floor_height == 3.0
    assert inp.total_area == round(28.0 * 17.5 * 9, 1)
    assert inp.city == "Алматы"


def test_concept_respects_explicit_floors_and_default_type():
    inp = propose_concept(area_m2=500.0, length_m=30.0, width_m=20.0,
                          city="Астана", object_type="Неизвестный", floors=3)
    assert inp.floors == 3               # явное значение
    assert inp.object_type == "Неизвестный"
