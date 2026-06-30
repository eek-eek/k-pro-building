"""Сверка точки застройки с картой тектонических разломов и сейсмикой.

ВАЖНО: координаты разломов — ОРИЕНТИРОВОЧНЫЕ (по открытым геологическим данным),
не официальные изолинии и НЕ заменяют инженерно-геологические изыскания (ИГИ) и
сейсмомикрорайонирование по СП РК 2.03-30. Это инструмент раннего скрининга.

Чистая геометрия, работает офлайн, без сетевых зависимостей. Координаты GeoJSON —
[lon, lat], как и в остальном geo-коде проекта."""
from __future__ import annotations

import math

from ..schemas import FaultVerdict

M_PER_DEG_LAT = 111_320.0

# Сейсмическая интенсивность (баллы MSK-64) по городам — ориентир по картам ОСР РК.
CITY_INTENSITY = {
    "Алматы": 9, "Талдыкорган": 9, "Тараз": 9, "Шымкент": 8,
    "Усть-Каменогорск": 7, "Кызылорда": 7,
    "Астана": 6, "Караганда": 6, "Актобе": 6, "Атырау": 6, "Семей": 6,
    "Павлодар": 6, "Костанай": 6, "Уральск": 6, "Петропавловск": 6,
}
DEFAULT_INTENSITY = 6

# Буферы расстояния до разлома (м).
AVOID_M = 300.0       # фактически в зоне разрыва — капитальное здание не рекомендуем
CAUTION_M = 1500.0    # близко к разлому — повышенный риск, ограничиваем высоту
AVOID_FLOORS = 2      # вынужденная застройка в зоне разлома — только малоэтажно
NEAR_FLOORS = 5       # макс. этажность в зоне повышенного риска

SOURCE = "ориентировочный слой разломов (открытые геол. данные) — требуется ИГИ"

# Ориентировочные крупные активные разломы (LineString [lon, lat]).
# Приоритет — Алматинская сейсмозона. НЕ официальные изолинии.
FAULTS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "properties": {"name": "Заилийский (фронтальный) разлом", "activity": "активный"},
         "geometry": {"type": "LineString", "coordinates": [
             [76.55, 43.13], [76.75, 43.15], [76.95, 43.18],
             [77.15, 43.21], [77.40, 43.25]]}},
        {"type": "Feature",
         "properties": {"name": "Алматинский разлом", "activity": "активный"},
         "geometry": {"type": "LineString", "coordinates": [
             [76.70, 43.20], [76.85, 43.24], [77.00, 43.27], [77.15, 43.30]]}},
        {"type": "Feature",
         "properties": {"name": "Чилико-Кеминская зона", "activity": "активный"},
         "geometry": {"type": "LineString", "coordinates": [
             [77.20, 43.00], [77.70, 42.95], [78.20, 42.88], [78.70, 42.80]]}},
    ],
}


def _seismic_floor_cap(balls: int) -> int | None:
    """Ориентировочный предел этажности по сейсмике (индикативно; точные значения —
    по СП РК 2.03-30 для конкретной конструктивной схемы)."""
    if balls >= 10:
        return 5
    if balls == 9:
        return 9
    if balls == 8:
        return 12
    if balls == 7:
        return 16
    return None  # ≤6 баллов — сейсмика этажность на нашем уровне не лимитирует


def _dist_point_seg_m(lat: float, lon: float,
                      a: list[float], b: list[float]) -> float:
    """Расстояние от точки до отрезка [a,b] (м) в локальной плоской проекции.
    a, b — [lon, lat]."""
    mx = M_PER_DEG_LAT * math.cos(math.radians(lat))
    px, py = lon * mx, lat * M_PER_DEG_LAT
    ax, ay = a[0] * mx, a[1] * M_PER_DEG_LAT
    bx, by = b[0] * mx, b[1] * M_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def nearest_fault(lat: float, lon: float) -> tuple[str, float]:
    """(имя ближайшего разлома, расстояние в метрах)."""
    best_name, best_d = "", float("inf")
    for f in FAULTS["features"]:
        coords = f["geometry"]["coordinates"]
        for i in range(len(coords) - 1):
            d = _dist_point_seg_m(lat, lon, coords[i], coords[i + 1])
            if d < best_d:
                best_d, best_name = d, f["properties"]["name"]
    return best_name, best_d


def assess_faults(lat: float, lon: float, city: str = "") -> FaultVerdict:
    """Скрининг точки: разломный + сейсмический риск → статус и предел этажности."""
    balls = CITY_INTENSITY.get(city, DEFAULT_INTENSITY)
    seis_cap = _seismic_floor_cap(balls)
    name, dist = nearest_fault(lat, lon)
    dist_i = int(round(dist))

    if dist <= AVOID_M:
        return FaultVerdict(
            status="avoid", nearest_fault=name, distance_m=dist_i, intensity=balls,
            max_floors=AVOID_FLOORS, source=SOURCE,
            note=(f"Точка в зоне разлома «{name}» (~{dist_i} м). Капитальное строительство "
                  f"не рекомендуется: вынесите пятно за пределы зоны разрыва либо проведите "
                  f"спец. ИГИ и сейсмомикрорайонирование. При вынужденной застройке — только "
                  f"малоэтажно (до {AVOID_FLOORS} эт.)."))

    if dist <= CAUTION_M:
        max_floors = min(NEAR_FLOORS, seis_cap or NEAR_FLOORS)
        return FaultVerdict(
            status="caution", nearest_fault=name, distance_m=dist_i, intensity=balls,
            max_floors=max_floors, source=SOURCE,
            note=(f"Близко к разлому «{name}» (~{dist_i} м), сейсмичность {balls} баллов. "
                  f"Повышенный риск — рекомендуем ограничить высоту до {max_floors} эт. и "
                  f"предусмотреть усиленную сейсмозащиту (СП РК 2.03-30)."))

    if seis_cap is not None:
        note = (f"Активных разломов рядом нет (ближайший «{name}» ~{dist_i} м). "
                f"Сейсмичность {balls} баллов — этажность ориентировочно до {seis_cap} эт. "
                f"(уточнить по СП РК 2.03-30).")
    else:
        note = (f"Активных разломов рядом нет (ближайший «{name}» ~{dist_i} м), "
                f"сейсмичность невысокая ({balls} баллов) — особых ограничений по высоте нет.")
    return FaultVerdict(status="ok", nearest_fault=name, distance_m=dist_i,
                        intensity=balls, max_floors=seis_cap, note=note, source=SOURCE)
