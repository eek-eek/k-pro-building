# SP2 — Проверка участка по генплану/кадастру Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Кнопка «Проверить участок» на карточке объекта запрашивает национальный геопортал (map.gov.kz, GeoServer WFS) по координате и выдаёт вердикт зоны (разрешено/ограничено/не проверено) с целевым назначением участка, предупреждением о несоответствии типу и WMS-наложением кадастра/зон на карту.

**Architecture:** Изолированный адаптер `app/zoning/` (`WfsZoningProvider` поверх stdlib `urllib`, мягкая деградация на «не проверено»), ray-casting point-in-polygon в `app/geo.py` (без shapely), эвристика назначение↔тип. Вердикт кэшируется в новых колонках `zone_*` таблицы `building_objects` (идемпотентный ALTER-guard). Фронт — кнопка/бейдж на карточке + WMS overlay (Leaflet core). Сеть в тестах запрещена → весь WFS мокается.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (SQLite), Pydantic v2, pytest; Leaflet `L.tileLayer.wms`. Backend-команды из `backend/`, интерпретатор `.venv/bin/python`; тесты `.venv/bin/python -m pytest -q`; фронт — `node --check`.

**Контекст:**
- Адаптер по образцу `app/pricesource/` (фабрика `get_*` + провайдер + мягкая деградация).
- WFS (валидировано спайком 2026-06-28): `GET https://map.gov.kz/geoserver/ows?service=WFS&version=2.0.0&request=GetFeature&typeNames=openmap:land_plots&outputFormat=application/json&srsName=EPSG:4326&count=5&bbox=<lat-d>,<lon-d>,<lat+d>,<lon+d>,urn:ogc:def:crs:EPSG::4326`. Ответ — GeoJSON FeatureCollection; у land_plots свойства `kad_nomer`, `tsn_ru` (целевое назначение), `squ`; геометрия MultiPolygon [lon,lat].
- Миграция новых колонок — как `_ensure_estimate_object_id` в `app/database.py` (PRAGMA + ALTER).
- conftest: `LLM_PROVIDER=demo`, сеть не дёргать — все HTTP в тестах через monkeypatch.

---

## File Structure
- Create: `backend/app/zoning/__init__.py`, `backend/app/zoning/base.py`, `backend/app/zoning/wfs.py`, `backend/app/zoning/heuristics.py`
- Modify: `backend/app/geo.py` (point_in_polygon), `backend/app/models.py` (zone_* колонки), `backend/app/database.py` (ALTER-guard), `backend/app/schemas.py` (ZoneVerdict), `backend/app/api/routes.py` (эндпоинты + get_object), `frontend/app.js`, `frontend/styles.css`
- Test: `backend/tests/test_geo.py` (дописать), `backend/tests/test_zoning.py` (создать), `backend/tests/test_objects_api.py` (дописать)

---

## Task 1: `geo.point_in_polygon` (ray-casting, без shapely)

**Files:** Modify `backend/app/geo.py`; Test `backend/tests/test_geo.py`

- [ ] **Step 1: Падающий тест** — дописать в `backend/tests/test_geo.py`:
```python
from app.geo import point_in_polygon

SQUARE = {"type": "Polygon", "coordinates": [[
    [76.90, 43.24], [76.91, 43.24], [76.91, 43.25], [76.90, 43.25], [76.90, 43.24]]]}
MULTI = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}


def test_point_in_polygon_inside_and_outside():
    assert point_in_polygon(76.905, 43.245, SQUARE) is True
    assert point_in_polygon(76.80, 43.20, SQUARE) is False


def test_point_in_polygon_multipolygon():
    assert point_in_polygon(76.905, 43.245, MULTI) is True
    assert point_in_polygon(76.95, 43.30, MULTI) is False
```

- [ ] **Step 2: Запустить — упадёт** (`ImportError: point_in_polygon`).
Run: `.venv/bin/python -m pytest tests/test_geo.py -q`

- [ ] **Step 3: Реализовать** — добавить в конец `backend/app/geo.py`:
```python
def _ring_contains(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray-casting: точка (lon,lat) внутри кольца GeoJSON [lon,lat]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, geometry: dict) -> bool:
    """Содержит ли GeoJSON Polygon/MultiPolygon точку. Внешнее кольцо; дырки
    игнорируем (для проверки попадания в участок/зону этого достаточно)."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        return bool(coords) and _ring_contains(lon, lat, coords[0])
    if gtype == "MultiPolygon":
        return any(poly and _ring_contains(lon, lat, poly[0]) for poly in coords)
    return False
```

- [ ] **Step 4: Запустить — пройдёт.** Run: `.venv/bin/python -m pytest tests/test_geo.py -q`
- [ ] **Step 5: Коммит**
```bash
cd /Users/eek/Docs/kpro_case/mvp1/repo/k-pro-building
git add backend/app/geo.py backend/tests/test_geo.py
git commit -m "feat(geo): point_in_polygon (ray-casting, Polygon/MultiPolygon)"
```

---

## Task 2: Эвристика «целевое назначение ↔ тип объекта»

**Files:** Create `backend/app/zoning/__init__.py` (пустой пакет-маркер на этом шаге), `backend/app/zoning/heuristics.py`; Test `backend/tests/test_zoning.py`

- [ ] **Step 1: Падающий тест** — `backend/tests/test_zoning.py`:
```python
from app.zoning.heuristics import use_mismatch_warning


def test_warns_on_greening_plot_for_building():
    w = use_mismatch_warning("для благоустройства и озеленения территории", "Жилой дом")
    assert w and "назначени" in w.lower()


def test_no_warning_when_purpose_allows_construction():
    assert use_mismatch_warning("для строительства жилого комплекса", "Жилой дом") is None


def test_no_warning_when_purpose_unknown_or_empty():
    assert use_mismatch_warning("", "Жилой дом") is None
```

- [ ] **Step 2: Запустить — упадёт** (`ModuleNotFoundError: app.zoning`).
Run: `.venv/bin/python -m pytest tests/test_zoning.py -q`

- [ ] **Step 3a: Создать пакет** — пустой файл `backend/app/zoning/__init__.py` (содержимое допишем в Task 3):
```python
"""Адаптер проверки участка по геопорталу (зонирование/кадастр РК)."""
```

- [ ] **Step 3b: Реализовать** — `backend/app/zoning/heuristics.py`:
```python
"""Сверка целевого назначения участка (tsn_ru) с типом строящегося объекта.
Консервативно: предупреждаем только при ЯВНОМ несоответствии — чтобы не плодить
ложные тревоги. Эвристика по ключевым словам, не юридическое заключение."""
from __future__ import annotations

from typing import Optional

# Назначения, которые обычно НЕ допускают капитальное здание данного типа.
_STOP_MARKERS = (
    "озеленен", "благоустройств", "сельскохозяйствен", "нестационарн",
    "временн", "парк", "сквер", "водн", "автостоянк", "паркинг",
)
# Если назначение про стройку — стоп-маркеры не применяем.
_CONSTRUCTION_MARKERS = ("строительств", "застрой", "возведен")
# Типы объектов, для которых сверка осмысленна (капитальные здания).
_BUILDING_TYPES = ("Жилой дом", "Общественное здание", "Промышленное здание", "Офис")


def use_mismatch_warning(land_use: str, object_type: str) -> Optional[str]:
    """Вернуть текст предупреждения, если назначение участка явно не вяжется с
    типом объекта; иначе None."""
    lu = (land_use or "").lower().strip()
    if not lu or object_type not in _BUILDING_TYPES:
        return None
    if any(m in lu for m in _CONSTRUCTION_MARKERS):
        return None
    if any(m in lu for m in _STOP_MARKERS):
        return (f"Целевое назначение участка («{land_use}») может не допускать "
                f"капитальное строительство ({object_type}) — уточните в акимате/ГАСК.")
    return None
```

- [ ] **Step 4: Запустить — пройдёт.** Run: `.venv/bin/python -m pytest tests/test_zoning.py -q`
- [ ] **Step 5: Коммит**
```bash
git add backend/app/zoning/__init__.py backend/app/zoning/heuristics.py backend/tests/test_zoning.py
git commit -m "feat(zoning): эвристика сверки назначения участка с типом объекта"
```

---

## Task 3: `ZoneVerdict` + `WfsZoningProvider` (WFS, мокается)

**Files:** Modify `backend/app/schemas.py`, `backend/app/zoning/__init__.py`; Create `backend/app/zoning/base.py`, `backend/app/zoning/wfs.py`; Test `backend/tests/test_zoning.py`

- [ ] **Step 1: Дописать падающие тесты** в `backend/tests/test_zoning.py`:
```python
from app.zoning import get_zoning_provider
from app.zoning import wfs as wfs_mod
from app.schemas import ZoneVerdict

ALMATY = (43.238, 76.945)

_PLOT = {"features": [{
    "geometry": {"type": "MultiPolygon", "coordinates": [[[
        [76.944, 43.237], [76.946, 43.237], [76.946, 43.239], [76.944, 43.239], [76.944, 43.237]]]]},
    "properties": {"kad_nomer": "20313005104",
                   "tsn_ru": "для строительства жилого комплекса", "squ": 5000}}]}
_EMPTY = {"features": []}


def _fake_wfs(monkeypatch, by_layer):
    def fake(typename, lat, lon, count=5):
        return by_layer.get(typename, _EMPTY)
    monkeypatch.setattr(wfs_mod, "_wfs_features", fake)


def test_verdict_allowed_with_land_use(monkeypatch):
    _fake_wfs(monkeypatch, {"openmap:land_plots": _PLOT})
    v = get_zoning_provider().check(*ALMATY, object_type="Жилой дом")
    assert isinstance(v, ZoneVerdict)
    assert v.status == "allowed"
    assert v.kad_nomer == "20313005104"
    assert "жилого" in v.land_use


def test_verdict_restricted_in_water_zone(monkeypatch):
    _fake_wfs(monkeypatch, {"openmap:land_plots": _PLOT,
                            "geonode:almaty_waterprotectionzone": _PLOT})
    v = get_zoning_provider().check(*ALMATY, object_type="Жилой дом", city="Алматы")
    assert v.status == "restricted"
    assert "водоохран" in v.zone.lower()


def test_verdict_unknown_when_no_plot(monkeypatch):
    _fake_wfs(monkeypatch, {})
    v = get_zoning_provider().check(*ALMATY, object_type="Жилой дом")
    assert v.status == "unknown"


def test_verdict_warns_on_mismatch(monkeypatch):
    plot = {"features": [{**_PLOT["features"][0],
            "properties": {**_PLOT["features"][0]["properties"],
                           "tsn_ru": "для благоустройства и озеленения территории"}}]}
    _fake_wfs(monkeypatch, {"openmap:land_plots": plot})
    v = get_zoning_provider().check(*ALMATY, object_type="Жилой дом")
    assert v.status == "allowed" and v.note  # предупреждение в note


def test_verdict_unknown_on_wfs_failure(monkeypatch):
    def boom(typename, lat, lon, count=5):
        raise OSError("network down")
    monkeypatch.setattr(wfs_mod, "_wfs_features", boom)
    v = get_zoning_provider().check(*ALMATY, object_type="Жилой дом")
    assert v.status == "unknown"
```

- [ ] **Step 2: Запустить — упадёт.** Run: `.venv/bin/python -m pytest tests/test_zoning.py -q`

- [ ] **Step 3a: Схема** — в `backend/app/schemas.py` после `class ObjectCard(...)` добавить:
```python
class ZoneVerdict(BaseModel):
    status: str                       # allowed | restricted | unknown
    land_use: str = ""                # целевое назначение (tsn_ru)
    kad_nomer: str = ""
    zone: str = ""                    # "водоохранная зона" | "кадастровый участок" | ""
    source: str = "map.gov.kz/geoserver (WFS)"
    note: str = ""
    checked_at: Optional[str] = None
```

- [ ] **Step 3b: Контракт провайдера** — `backend/app/zoning/base.py`:
```python
"""Контракт провайдера проверки зоны участка."""
from __future__ import annotations

from ..schemas import ZoneVerdict


class ZoningProvider:
    name: str = "base"

    def check(self, lat: float, lon: float, object_type: str = "",
              city: str = "") -> ZoneVerdict:  # pragma: no cover
        raise NotImplementedError
```

- [ ] **Step 3c: WFS-провайдер** — `backend/app/zoning/wfs.py`:
```python
"""WfsZoningProvider: проверка участка по национальному GeoServer (map.gov.kz).
WFS 2.0, GeoJSON, EPSG:4326. Точечный запрос через малый bbox. Мягкая деградация:
сеть/портал недоступны → status=unknown (процесс не падает)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from ..geo import point_in_polygon
from ..schemas import ZoneVerdict
from .base import ZoningProvider
from .heuristics import use_mismatch_warning

WFS_BASE = "https://map.gov.kz/geoserver/ows"
LAND_PLOTS = "openmap:land_plots"
WATER_LAYER_BY_CITY = {"Алматы": "geonode:almaty_waterprotectionzone"}
_DELTA = 0.00015  # ~15 м: bbox вокруг точки
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


def _wfs_features(typename: str, lat: float, lon: float, count: int = 5) -> dict:
    """Сырой WFS GetFeature → GeoJSON dict. Вынесено для подмены в тестах."""
    bbox = f"{lat - _DELTA},{lon - _DELTA},{lat + _DELTA},{lon + _DELTA},urn:ogc:def:crs:EPSG::4326"
    qs = urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": typename, "outputFormat": "application/json",
        "srsName": "EPSG:4326", "count": count, "bbox": bbox,
    })
    req = urllib.request.Request(f"{WFS_BASE}?{qs}", headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _containing(features: list[dict], lat: float, lon: float) -> dict | None:
    for f in features:
        geom = f.get("geometry") or {}
        if point_in_polygon(lon, lat, geom):
            return f
    return features[0] if features else None  # ближайший по bbox, если ни один не накрыл


class WfsZoningProvider(ZoningProvider):
    name = "map.gov.kz-wfs"

    def check(self, lat: float, lon: float, object_type: str = "",
              city: str = "") -> ZoneVerdict:
        # 1. Участок (land_plots)
        try:
            plots = _wfs_features(LAND_PLOTS, lat, lon).get("features", [])
        except Exception:
            return ZoneVerdict(status="unknown",
                               note="Геопортал не ответил — проверьте участок вручную.")
        plot = _containing(plots, lat, lon)

        # 2. Водоохранная зона (если для города есть слой)
        water_layer = WATER_LAYER_BY_CITY.get(city)
        if water_layer:
            try:
                wf = _wfs_features(water_layer, lat, lon).get("features", [])
            except Exception:
                wf = []
            if _containing(wf, lat, lon) is not None:
                return ZoneVerdict(status="restricted", zone="водоохранная зона",
                                   land_use=(plot or {}).get("properties", {}).get("tsn_ru", ""),
                                   kad_nomer=(plot or {}).get("properties", {}).get("kad_nomer", ""),
                                   note="Участок в водоохранной зоне — застройка ограничена.")

        # 3. Нет участка → не проверено
        if plot is None:
            return ZoneVerdict(status="unknown", zone="",
                               note="Участок не найден в кадастре — свободная земля или нет данных; проверьте вручную.")

        # 4. Участок есть → разрешено + детали + сверка назначения
        props = plot.get("properties", {})
        land_use = props.get("tsn_ru") or ""
        warning = use_mismatch_warning(land_use, object_type)
        return ZoneVerdict(status="allowed", zone="кадастровый участок",
                           land_use=land_use, kad_nomer=props.get("kad_nomer") or "",
                           note=warning or "")
```

- [ ] **Step 3d: Фабрика** — заменить содержимое `backend/app/zoning/__init__.py` на:
```python
"""Адаптер проверки участка по геопорталу (зонирование/кадастр РК)."""
from __future__ import annotations

from .base import ZoningProvider
from .wfs import WfsZoningProvider

_PROVIDER: ZoningProvider | None = None


def get_zoning_provider() -> ZoningProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = WfsZoningProvider()
    return _PROVIDER
```

- [ ] **Step 4: Запустить — пройдёт.** Run: `.venv/bin/python -m pytest tests/test_zoning.py -q`
- [ ] **Step 5: Коммит**
```bash
git add backend/app/schemas.py backend/app/zoning/ backend/tests/test_zoning.py
git commit -m "feat(zoning): WfsZoningProvider + ZoneVerdict (WFS map.gov.kz, мягкая деградация)"
```

---

## Task 4: Колонки `zone_*` на `building_objects` + миграция-guard

**Files:** Modify `backend/app/models.py`, `backend/app/database.py`; Test `backend/tests/test_objects_api.py`

- [ ] **Step 1: Падающий тест** — дописать в `backend/tests/test_objects_api.py`:
```python
def test_building_object_has_zone_columns():
    run_seed()
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(building_objects)")]
    for c in ("zone_status", "zone_land_use", "zone_kad_nomer", "zone_note", "zone_checked_at"):
        assert c in cols, f"нет колонки {c}"
```

- [ ] **Step 2: Запустить — упадёт.** Run: `.venv/bin/python -m pytest tests/test_objects_api.py::test_building_object_has_zone_columns -q`

- [ ] **Step 3a: Модель** — в классе `BuildingObject` (`models.py`), после строки `notes: Mapped[str] = mapped_column(Text, default="")` добавить:
```python
    zone_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # allowed|restricted|unknown
    zone_land_use: Mapped[str] = mapped_column(Text, default="")
    zone_kad_nomer: Mapped[str] = mapped_column(String(64), default="")
    zone_note: Mapped[str] = mapped_column(Text, default="")
    zone_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 3b: Миграция-guard** — в `backend/app/database.py` в `init_db()` после `_ensure_estimate_object_id()` добавить вызов `_ensure_building_object_zone_cols()`, и добавить функцию:
```python
def _ensure_building_object_zone_cols() -> None:
    """Идемпотентно добавить zone_* в building_objects (SQLite create_all не
    добавляет колонки в существующую таблицу — БД dev из SP1 их не имеет)."""
    if not settings.database_url.startswith("sqlite"):
        return
    add = {
        "zone_status": "VARCHAR(16)", "zone_land_use": "TEXT DEFAULT ''",
        "zone_kad_nomer": "VARCHAR(64) DEFAULT ''", "zone_note": "TEXT DEFAULT ''",
        "zone_checked_at": "DATETIME",
    }
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(building_objects)")]
        if not cols:
            return
        for name, ddl in add.items():
            if name not in cols:
                conn.exec_driver_sql(f"ALTER TABLE building_objects ADD COLUMN {name} {ddl}")
```

- [ ] **Step 4: Запустить — пройдёт.** Run: `.venv/bin/python -m pytest tests/test_objects_api.py::test_building_object_has_zone_columns -q`
- [ ] **Step 5: Коммит**
```bash
git add backend/app/models.py backend/app/database.py backend/tests/test_objects_api.py
git commit -m "feat(models): zone_* на building_objects (+ migration guard)"
```

---

## Task 5: Эндпоинты `check-zone` + `zoning/wms` + zone_* в карточке

**Files:** Modify `backend/app/api/routes.py`; Test `backend/tests/test_objects_api.py`

- [ ] **Step 1: Дописать падающие тесты** в `backend/tests/test_objects_api.py` (вверху рядом с другими импортами добавить `from app.zoning import wfs as _wfs`):
```python
def test_check_zone_saves_verdict(monkeypatch):
    plot = {"features": [{
        "geometry": {"type": "MultiPolygon", "coordinates": [[[
            [76.944, 43.237], [76.946, 43.237], [76.946, 43.239], [76.944, 43.239], [76.944, 43.237]]]]},
        "properties": {"kad_nomer": "20313005104",
                       "tsn_ru": "для строительства жилого дома", "squ": 5000}}]}
    monkeypatch.setattr(_wfs, "_wfs_features",
                        lambda tn, lat, lon, count=5: plot if tn == "openmap:land_plots" else {"features": []})
    oid = client.post("/api/objects", json={
        "name": "Z", "city": "Алматы", "lat": 43.238, "lon": 76.945, "polygon": POLY}).json()["id"]
    v = client.post(f"/api/objects/{oid}/check-zone").json()
    assert v["status"] == "allowed" and v["kad_nomer"] == "20313005104"
    # вердикт сохранён и виден в карточке
    got = client.get(f"/api/objects/{oid}").json()
    assert got["zone_status"] == "allowed"
    assert "жилого" in got["zone_land_use"]


def test_check_zone_404_for_missing_object():
    assert client.post("/api/objects/999999/check-zone").status_code == 404


def test_zoning_wms_config():
    cfg = client.get("/api/zoning/wms", params={"city": "Алматы"}).json()
    assert cfg["url"] and cfg["layers"]
```

- [ ] **Step 2: Запустить — упадёт.** Run: `.venv/bin/python -m pytest tests/test_objects_api.py::test_check_zone_saves_verdict -q`

- [ ] **Step 3a: Импорты** — в `backend/app/api/routes.py` рядом с другими `from ..` добавить:
```python
from ..zoning import get_zoning_provider
from ..zoning.wfs import WFS_BASE, LAND_PLOTS, WATER_LAYER_BY_CITY
```
И добавить `ZoneVerdict` в существующий `from ..schemas import ( ... )`.

- [ ] **Step 3b: Эндпоинты** — в конец `backend/app/api/routes.py` добавить:
```python
@router.post("/objects/{object_id}/check-zone")
def check_zone(object_id: int, db: Session = Depends(get_db)) -> dict:
    obj = db.get(BuildingObject, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="object not found")
    # Объект не несёт object_type (его несёт смета) — для сверки назначения берём
    # типовой «Жилой дом»; эвристика консервативна, ложных тревог не плодит.
    verdict = get_zoning_provider().check(obj.lat, obj.lon, "Жилой дом", obj.city)
    obj.zone_status = verdict.status
    obj.zone_land_use = verdict.land_use
    obj.zone_kad_nomer = verdict.kad_nomer
    obj.zone_note = verdict.note
    obj.zone_checked_at = _utcnow_dt()
    db.commit()
    verdict.checked_at = obj.zone_checked_at.isoformat(timespec="seconds")
    return to_jsonable(verdict)


@router.get("/zoning/wms")
def zoning_wms(city: str = "Алматы") -> dict:
    layers = [LAND_PLOTS]
    water = WATER_LAYER_BY_CITY.get(city)
    if water:
        layers.append(water)
    return {"url": WFS_BASE, "layers": ",".join(layers), "format": "image/png", "transparent": True}
```

- [ ] **Step 3c: Хелпер времени** — вверху `routes.py` (рядом с другими хелперами) добавить:
```python
import datetime as _dt
def _utcnow_dt() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)
```

- [ ] **Step 3d: zone_* в карточке** — в `get_estimate`-соседнем `get_object` (`routes.py`) расширить возвращаемый dict, добавив перед `"estimates": [...]`:
```python
        "zone_status": obj.zone_status,
        "zone_land_use": obj.zone_land_use or "",
        "zone_kad_nomer": obj.zone_kad_nomer or "",
        "zone_note": obj.zone_note or "",
        "zone_checked_at": obj.zone_checked_at.isoformat(timespec="seconds") if obj.zone_checked_at else None,
```

- [ ] **Step 4: Запустить весь набор.** Run: `.venv/bin/python -m pytest -q` (зелёное).
- [ ] **Step 5: Коммит**
```bash
git add backend/app/api/routes.py backend/tests/test_objects_api.py
git commit -m "feat(api): check-zone + zoning/wms + zone_* в карточке объекта"
```

---

## Task 6: Фронт — кнопка проверки, бейдж вердикта, WMS-наложение

**Files:** Modify `frontend/app.js`, `frontend/styles.css`

- [ ] **Step 1: Api-методы** — в `app.js`, в объект `Api`, после `objectCreateEstimate: ...` добавить:
```javascript
  checkZone: (id) => api("POST", `/objects/${id}/check-zone`),
  zoningWms: (city) => api("GET", `/zoning/wms?city=${encodeURIComponent(city)}`),
```

- [ ] **Step 2: WMS overlay на карте объекта** — в `viewObject(id)` (`app.js`), после создания `map`
и `L.control.layers(layers).addTo(map)`, добавить overlay-слой кадастра/зон:
```javascript
  try {
    const wms = await Api.zoningWms(o.city);
    const overlay = L.tileLayer.wms(wms.url, {
      layers: wms.layers, format: wms.format, transparent: true, opacity: 0.5, attribution: "© map.gov.kz",
    });
    L.control.layers(layers, { "Кадастр/зоны": overlay }).addTo(map);
  } catch (e) { /* нет слоя — не критично */ }
```
(заменяет прежний `L.control.layers(layers).addTo(map)` — оставить только новый вызов с overlay).

- [ ] **Step 3: Блок «Генплан/кадастр»** — в `viewObject` в разметку левой колонки, между `#omap` и
`#conceptBox`, добавить контейнер `<div id="zoneBox"></div>`; затем после отрисовки карты вызвать
`renderZone(id, o)`. Добавить функции:
```javascript
function zoneBadge(status) {
  const map = { allowed: ["ok", "разрешено"], restricted: ["rejected", "ограничено"], unknown: ["draft", "не проверено"] };
  const [cls, label] = map[status] || map.unknown;
  return `<span class="sbadge ${cls}">${label}</span>`;
}

async function renderZone(id, o) {
  const box = document.getElementById("zoneBox");
  const has = o.zone_status;
  box.innerHTML = `<div class="concept-panel"><h3>Генплан / кадастр</h3>
    <div class="zone-line">${has ? zoneBadge(o.zone_status) : `<span class="hint">Участок ещё не проверялся.</span>`}
      <button class="btn ${has ? "" : "accent"}" id="zoneBtn" style="margin-left:auto">${has ? "Перепроверить" : "Проверить участок"}</button></div>
    <div id="zoneDetails">${zoneDetails(o)}</div></div>`;
  document.getElementById("zoneBtn").addEventListener("click", async () => {
    const btn = document.getElementById("zoneBtn"); btn.disabled = true; btn.textContent = "Проверяю…";
    try {
      const v = await Api.checkZone(id);
      Object.assign(o, { zone_status: v.status, zone_land_use: v.land_use,
        zone_kad_nomer: v.kad_nomer, zone_note: v.note, zone_checked_at: v.checked_at });
      toast("Проверка выполнена");
      renderZone(id, o);
    } catch (e) { toast(e.detail || "Ошибка проверки", true); btn.disabled = false; btn.textContent = "Проверить участок"; }
  });
}

function zoneDetails(o) {
  if (!o.zone_status) return "";
  const rows = [];
  if (o.zone_kad_nomer) rows.push(`<div class="meta">Кад. номер: <b>${escapeHtml(o.zone_kad_nomer)}</b></div>`);
  if (o.zone_land_use) rows.push(`<div class="meta">Назначение: ${escapeHtml(o.zone_land_use)}</div>`);
  if (o.zone_note) rows.push(`<div class="zone-warn">⚠ ${escapeHtml(o.zone_note)}</div>`);
  rows.push(`<div class="meta muted">Источник: map.gov.kz (WFS)${o.zone_checked_at ? " · " + escapeHtml(o.zone_checked_at) : ""}</div>`);
  return rows.join("");
}
```

- [ ] **Step 4: CSS** — в конец `frontend/styles.css`:
```css
.zone-line { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.zone-warn { color: var(--warn); background: var(--warn-bg); border-radius: var(--radius);
  padding: 8px 12px; font-size: 13px; margin: 6px 0; }
```

- [ ] **Step 5: Проверка** — `node --check frontend/app.js` → OK; перезапустить сервер; на карточке
объекта появляется блок «Генплан/кадастр» с кнопкой; на карте — тумблер «Кадастр/зоны».
(`curl -s http://127.0.0.1:8000/app.js | grep -c 'function renderZone'` → 1.)
- [ ] **Step 6: Коммит**
```bash
git add frontend/app.js frontend/styles.css
git commit -m "feat(frontend): проверка участка по генплану/кадастру — кнопка, бейдж, WMS-слой"
```

---

## Definition of Done (SP2)
- `point_in_polygon` (geo) и эвристика назначения покрыты unit-тестами.
- `WfsZoningProvider` отдаёт вердикт `allowed/restricted/unknown` с мягкой деградацией; все WFS-вызовы в тестах замоканы (сеть не дёргается).
- Колонки `zone_*` на `building_objects` (миграция-guard на dev-БД из SP1); весь набор тестов зелёный.
- `POST /objects/{id}/check-zone` сохраняет вердикт; `GET /objects/{id}` отдаёт `zone_*`; `GET /zoning/wms` даёт конфиг слоя.
- Фронт: на карточке объекта кнопка «Проверить участок» → бейдж + детали (назначение, кад. номер, предупреждение); на карте — переключаемый WMS-слой кадастра/зон.
- Ручной смоук (вне тестов): реальная проверка координаты в Алматы/Астане через живой WFS.
- Регрессия SP1 зелёная.

## Self-Review
- **Покрытие спеки:** источник WFS map.gov.kz ✓ (Task 3), land_plots+tsn_ru/kad_nomer ✓, водоохранные зоны ✓, вердикт allowed/restricted/unknown ✓, мягкая деградация ✓, сверка назначения ✓ (Task 2), кэш на объекте ✓ (Task 4), API check-zone+wms ✓ (Task 5), фронт кнопка+бейдж+WMS ✓ (Task 6). point_in_polygon ✓ (Task 1).
- **Типы согласованы:** `_wfs_features(typename, lat, lon, count)` — одинаковая сигнатура в wfs.py и в моках тестов; `ZoneVerdict` поля совпадают между схемой, провайдером, API и фронтом (status/land_use/kad_nomer/zone/note/checked_at).
- **Без плейсхолдеров:** весь код приведён.
