"""Параметрический концепт здания («макет») под участок → BuildingInput.
Только параметры (без 3D/планов); значения ориентировочные, пользователь правит."""
from __future__ import annotations

from .calc.forms import footprint_factor
from .schemas import BuildingInput

TYPICAL_FLOORS = {"Жилой дом": 9, "Общественное здание": 5, "Промышленное здание": 2}
SETBACK = 0.7  # габарит здания = bbox участка × 0.7 (~15% отступ с каждой стороны)


def propose_concept(area_m2: float, length_m: float, width_m: float,
                    city: str, object_type: str, floors: int | None = None,
                    form: str = "box") -> BuildingInput:
    b_len = round(length_m * SETBACK, 1)
    b_wid = round(width_m * SETBACK, 1)
    n = floors or TYPICAL_FLOORS.get(object_type, 5)
    # Форма меняет долю застройки → общую площадь (двор/башня → меньше).
    total = round(b_len * b_wid * footprint_factor(form) * n, 1)
    return BuildingInput(
        city=city,
        object_type=object_type,
        floors=n,
        floor_height=3.0,
        building_length=b_len,
        building_width=b_wid,
        total_area=total,
        form=form,
    )
