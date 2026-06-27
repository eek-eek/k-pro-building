"""Геометрия участка из GeoJSON-полигона (локальное приближение «плоской земли»).
Без shapely/pyproj — простая тригонометрия. Координаты GeoJSON: [lon, lat]."""
from __future__ import annotations

import math

M_PER_DEG_LAT = 111_320.0


def _ring(polygon: dict) -> list[list[float]]:
    return polygon["coordinates"][0]


def bbox_dims_m(polygon: dict) -> tuple[float, float]:
    """(length, width) габаритов bounding box полигона в метрах; length >= width."""
    ring = _ring(polygon)
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    lat0 = sum(lats) / len(lats)
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    ew = (max(lons) - min(lons)) * m_per_deg_lon
    ns = (max(lats) - min(lats)) * M_PER_DEG_LAT
    length, width = (max(ew, ns), min(ew, ns))
    return round(length, 1), round(width, 1)


def polygon_area_m2(polygon: dict) -> float:
    """Площадь полигона (формула шнурков в проекции метров)."""
    ring = _ring(polygon)
    lat0 = sum(p[1] for p in ring) / len(ring)
    mx = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    my = M_PER_DEG_LAT
    pts = [(p[0] * mx, p[1] * my) for p in ring]
    s = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        s += x1 * y2 - x2 * y1
    return round(abs(s) / 2.0, 1)
