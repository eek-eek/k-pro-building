"""Производные геометрические параметры объекта."""
from __future__ import annotations

from dataclasses import dataclass

from ..schemas import BuildingInput
from .forms import facade_factor, footprint_factor


@dataclass
class Geometry:
    build_area: float       # площадь застройки, м²
    perimeter: float        # периметр, м
    total_height: float     # высота надземной части, м
    building_volume: float  # строительный объём, м³
    facade_area: float      # площадь наружных стен (фасада), м²
    total_area: float       # общая площадь, м²
    floors: int


def derive(inp: BuildingInput) -> Geometry:
    length = max(inp.building_length, 0.0)
    width = max(inp.building_width, 0.0)
    # Форма здания: footprint — доля застройки/кровли/фундамента; facade — длина
    # наружных стен. Брусок нейтрален (1.0/1.0).
    fp = footprint_factor(inp.form)
    ff = facade_factor(inp.form)
    build_area = length * width * fp
    perimeter = 2.0 * (length + width) * ff
    total_height = max(inp.floor_height, 0.0) * max(inp.floors, 1)
    facade_area = perimeter * total_height

    # Если габариты не заданы, оцениваем застройку из общей площади и этажности.
    if build_area <= 0 and inp.total_area > 0 and inp.floors > 0:
        build_area = inp.total_area / inp.floors
        side = build_area ** 0.5
        perimeter = 4.0 * side * ff
        facade_area = perimeter * total_height

    return Geometry(
        build_area=build_area,
        perimeter=perimeter,
        total_height=total_height,
        building_volume=build_area * total_height,
        facade_area=facade_area,
        total_area=inp.total_area,
        floors=max(inp.floors, 1),
    )
