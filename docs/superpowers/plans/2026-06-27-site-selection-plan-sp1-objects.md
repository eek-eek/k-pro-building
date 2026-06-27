# SP1 — Объекты + карта + концепт + привязка сметы Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Сущность «объект строительства» с местоположением на карте (Leaflet), ручное создание объекта, параметрический концепт здания под участок, и создание ресурсной сметы, привязанной к объекту.

**Architecture:** Backend — новая таблица `building_objects`, FK `Estimate.object_id` (миграция через идемпотентный ALTER), модули `geo.py` (габарит/площадь из GeoJSON, тригонометрия — без новых зависимостей) и `concept.py` (параметры здания → `BuildingInput`). API объектов + концепт + создание сметы (синхронный расчёт, чтобы концепт сразу попал в смету). Frontend — Leaflet (CDN) с OSM+спутник, рисование участка, карточка объекта с панелью концепта.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (SQLite), Pydantic v2, pytest; Leaflet + leaflet-draw (CDN). Все backend-команды из `backend/`, интерпретатор `.venv/bin/python`; тесты `.venv/bin/python -m pytest -q`; фронт — `node --check`.

**Контекст:**
- Модели — стиль SQLAlchemy 2.0 (`Mapped`/`mapped_column`), `Base` из `app.database`, `_utcnow`. См. `app/models.py`.
- `init_db()` в `app/database.py` делает `Base.metadata.create_all`; вызывается из `run_seed()` (стартап и тесты).
- Расчёт сметы: `resolve_norm_profile` (`app.norms.resolver`) → `build_estimate` (`app.calc`) → `create_version` (`app.versioning`, source="initial"); см. `create_estimate_sync` в `app/api/routes.py`.
- GeoJSON-полигон: `{"type":"Polygon","coordinates":[[[lon,lat],...]]}` (порядок lon,lat; кольцо замкнуто).

---

## File Structure
- Create: `backend/app/geo.py`, `backend/app/concept.py`
- Modify: `backend/app/models.py` (BuildingObject + Estimate.object_id), `backend/app/database.py` (ALTER-guard), `backend/app/schemas.py` (Object* схемы), `backend/app/api/routes.py` (эндпоинты)
- Test: `backend/tests/test_geo.py`, `backend/tests/test_concept.py`, `backend/tests/test_objects_api.py`
- Frontend: `frontend/index.html` (Leaflet CDN + nav), `frontend/app.js` (виды), `frontend/styles.css` (карта/панели)

---

## Task 1: Модуль геометрии `geo.py`

**Files:** Create `backend/app/geo.py`; Test `backend/tests/test_geo.py`

- [ ] **Step 1: Падающий тест** — `backend/tests/test_geo.py`:
```python
from app.geo import bbox_dims_m, polygon_area_m2

# прямоугольник в Алматы (~43.24 ш.): 0.001° долготы × 0.0005° широты
RECT = {"type": "Polygon", "coordinates": [[
    [76.900, 43.2400], [76.901, 43.2400], [76.901, 43.2405], [76.900, 43.2405], [76.900, 43.2400],
]]}


def test_bbox_dims_returns_length_ge_width_in_meters():
    length, width = bbox_dims_m(RECT)
    # долгота: 0.001 * 111320 * cos(43.24°) ≈ 81 м; широта: 0.0005 * 111320 ≈ 55.7 м
    assert 70 <= length <= 90
    assert 50 <= width <= 62
    assert length >= width


def test_polygon_area_matches_length_times_width():
    length, width = bbox_dims_m(RECT)
    area = polygon_area_m2(RECT)
    assert abs(area - length * width) < 0.15 * (length * width)
```

- [ ] **Step 2: Запустить — упадёт** (`ModuleNotFoundError: app.geo`).
Run: `.venv/bin/python -m pytest tests/test_geo.py -q`

- [ ] **Step 3: Реализовать** — `backend/app/geo.py`:
```python
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
```

- [ ] **Step 4: Запустить — пройдёт.** Run: `.venv/bin/python -m pytest tests/test_geo.py -q`
- [ ] **Step 5: Коммит**
```bash
cd /Users/eek/Docs/kpro_case/mvp1/repo/k-pro-building
git add backend/app/geo.py backend/tests/test_geo.py
git commit -m "feat(geo): габарит и площадь участка из GeoJSON"
```

---

## Task 2: Модель `BuildingObject` + `Estimate.object_id` + миграция-guard

**Files:** Modify `backend/app/models.py`, `backend/app/database.py`; Test `backend/tests/test_objects_api.py` (создаём файл, первый тест — про схему)

- [ ] **Step 1: Падающий тест** — `backend/tests/test_objects_api.py`:
```python
from app.database import SessionLocal, engine
from app.seed import run_seed
from app.models import BuildingObject, Estimate


def test_building_object_table_and_estimate_fk():
    run_seed()
    # колонка object_id есть в estimates
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(estimates)")]
    assert "object_id" in cols
    # объект создаётся и привязывается к смете
    db = SessionLocal()
    try:
        obj = BuildingObject(name="Тест", city="Алматы", lat=43.24, lon=76.9, area_m2=1000.0)
        db.add(obj); db.commit()
        est = Estimate(name="С", object_type="Жилой дом", city="Алматы", object_id=obj.id)
        db.add(est); db.commit()
        assert est.object_id == obj.id
    finally:
        db.close()
```

- [ ] **Step 2: Запустить — упадёт** (`ImportError: BuildingObject` / нет колонки).
Run: `.venv/bin/python -m pytest tests/test_objects_api.py::test_building_object_table_and_estimate_fk -q`

- [ ] **Step 3a: Добавить модель** — в `backend/app/models.py`, в КОНЕЦ файла (после класса `Job`):
```python
class BuildingObject(Base):
    """Объект строительства: местоположение, контур участка, концепт."""

    __tablename__ = "building_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    city: Mapped[str] = mapped_column(String(128), default="Алматы")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    polygon: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    area_m2: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|selected
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual|auto
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
```

- [ ] **Step 3b: Добавить FK в Estimate** — в классе `Estimate` (`models.py`), после строки `status: Mapped[str] = mapped_column(String(16), default="draft", index=True)` добавить:
```python
    object_id: Mapped[int | None] = mapped_column(
        ForeignKey("building_objects.id", ondelete="SET NULL"), nullable=True, index=True
    )
```

- [ ] **Step 3c: Миграция-guard** — в `backend/app/database.py` заменить функцию `init_db` на:
```python
def init_db() -> None:
    """Создать таблицы (модели импортируются ради регистрации в метаданных)."""
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_estimate_object_id()


def _ensure_estimate_object_id() -> None:
    """Идемпотентно добавить estimates.object_id на старой БД (SQLite create_all
    не добавляет колонки в существующие таблицы)."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(estimates)")]
        if cols and "object_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE estimates ADD COLUMN object_id INTEGER")
```

- [ ] **Step 4: Запустить — пройдёт.** Run: `.venv/bin/python -m pytest tests/test_objects_api.py::test_building_object_table_and_estimate_fk -q`
(Если падает из-за старой dev-БД — это тест-БД in-memory/файловая реседится; для локального сервера удалить `backend/data/ai_smeta.db`.)
- [ ] **Step 5: Коммит**
```bash
git add backend/app/models.py backend/app/database.py backend/tests/test_objects_api.py
git commit -m "feat(models): BuildingObject + Estimate.object_id (+ migration guard)"
```

---

## Task 3: Концепт здания `concept.py`

**Files:** Create `backend/app/concept.py`; Test `backend/tests/test_concept.py`

- [ ] **Step 1: Падающий тест** — `backend/tests/test_concept.py`:
```python
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
```

- [ ] **Step 2: Запустить — упадёт.** Run: `.venv/bin/python -m pytest tests/test_concept.py -q`

- [ ] **Step 3: Реализовать** — `backend/app/concept.py`:
```python
"""Параметрический концепт здания («макет») под участок → BuildingInput.
Только параметры (без 3D/планов); значения ориентировочные, пользователь правит."""
from __future__ import annotations

from .schemas import BuildingInput

TYPICAL_FLOORS = {"Жилой дом": 9, "Общественное здание": 5, "Промышленное здание": 2}
SETBACK = 0.7  # габарит здания = bbox участка × 0.7 (~15% отступ с каждой стороны)


def propose_concept(area_m2: float, length_m: float, width_m: float,
                    city: str, object_type: str, floors: int | None = None) -> BuildingInput:
    b_len = round(length_m * SETBACK, 1)
    b_wid = round(width_m * SETBACK, 1)
    n = floors or TYPICAL_FLOORS.get(object_type, 5)
    total = round(b_len * b_wid * n, 1)
    return BuildingInput(
        city=city,
        object_type=object_type,
        floors=n,
        floor_height=3.0,
        building_length=b_len,
        building_width=b_wid,
        total_area=total,
    )
```

- [ ] **Step 4: Запустить — пройдёт.** Run: `.venv/bin/python -m pytest tests/test_concept.py -q`
- [ ] **Step 5: Коммит**
```bash
git add backend/app/concept.py backend/tests/test_concept.py
git commit -m "feat(concept): параметрический концепт здания под участок"
```

---

## Task 4: Схемы + CRUD-эндпоинты объектов

**Files:** Modify `backend/app/schemas.py`, `backend/app/api/routes.py`; Test `backend/tests/test_objects_api.py`

- [ ] **Step 1: Дописать падающие тесты** в `backend/tests/test_objects_api.py`:
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

POLY = {"type": "Polygon", "coordinates": [[
    [76.900, 43.2400], [76.901, 43.2400], [76.901, 43.2405], [76.900, 43.2405], [76.900, 43.2400],
]]}


def test_object_crud():
    oid = client.post("/api/objects", json={
        "name": "Участок-1", "city": "Алматы", "lat": 43.24, "lon": 76.9, "polygon": POLY}).json()["id"]
    listing = client.get("/api/objects").json()
    assert any(o["id"] == oid and o["area_m2"] > 0 for o in listing)  # площадь из полигона
    got = client.get(f"/api/objects/{oid}").json()
    assert got["object"]["name"] == "Участок-1"
    client.patch(f"/api/objects/{oid}", json={"name": "Новый"})
    assert client.get(f"/api/objects/{oid}").json()["object"]["name"] == "Новый"
    assert client.delete(f"/api/objects/{oid}").status_code == 204
    assert client.get(f"/api/objects/{oid}").status_code == 404
```

- [ ] **Step 2: Запустить — упадёт.** Run: `.venv/bin/python -m pytest tests/test_objects_api.py::test_object_crud -q`

- [ ] **Step 3a: Схемы** — в `backend/app/schemas.py` после `class RecommendationAdd(...)` добавить:
```python
class ObjectCreate(BaseModel):
    name: str = ""
    city: str = "Алматы"
    lat: float
    lon: float
    polygon: Optional[dict] = None
    area_m2: float = 0.0
    notes: str = ""


class ObjectPatch(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    notes: Optional[str] = None


class ObjectCard(BaseModel):
    id: int
    name: str
    city: str
    lat: float
    lon: float
    area_m2: float
    status: str
    source: str
    score: Optional[float]
    estimate_count: int
    updated_at: str
```

- [ ] **Step 3b: Эндпоинты** — в `backend/app/api/routes.py`:
Импорты (рядом с другими `from ..`):
```python
import math
from ..geo import bbox_dims_m, polygon_area_m2
from ..concept import propose_concept
from ..models import BuildingObject
```
Добавить `ObjectCard, ObjectCreate, ObjectPatch` в существующий `from ..schemas import ( ... )`.
В конец файла добавить:
```python
def _object_card(db: Session, obj: BuildingObject) -> ObjectCard:
    cnt = db.query(Estimate).filter_by(object_id=obj.id).count()
    return ObjectCard(
        id=obj.id, name=obj.name, city=obj.city, lat=obj.lat, lon=obj.lon,
        area_m2=obj.area_m2, status=obj.status, source=obj.source, score=obj.score,
        estimate_count=cnt, updated_at=obj.updated_at.isoformat(timespec="seconds"),
    )


@router.get("/objects")
def list_objects(db: Session = Depends(get_db)) -> list[ObjectCard]:
    rows = db.scalars(select(BuildingObject).order_by(BuildingObject.updated_at.desc())).all()
    return [_object_card(db, o) for o in rows]


@router.post("/objects")
def create_object(body: ObjectCreate, db: Session = Depends(get_db)) -> dict:
    area = body.area_m2
    if not area and body.polygon:
        area = polygon_area_m2(body.polygon)
    obj = BuildingObject(name=body.name or "Объект", city=body.city, lat=body.lat,
                         lon=body.lon, polygon=body.polygon, area_m2=area, notes=body.notes)
    db.add(obj)
    db.commit()
    return {"id": obj.id}


@router.get("/objects/{object_id}")
def get_object(object_id: int, db: Session = Depends(get_db)) -> dict:
    obj = db.get(BuildingObject, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="object not found")
    ests = db.scalars(select(Estimate).where(Estimate.object_id == object_id)).all()
    return {
        "object": _object_card(db, obj).model_dump(),
        "polygon": obj.polygon,
        "notes": obj.notes,
        "estimates": [{"id": e.id, "name": e.name, "status": e.status,
                       "total": (e.current_version.total if e.current_version else 0.0)}
                      for e in ests],
    }


@router.patch("/objects/{object_id}")
def patch_object(object_id: int, body: ObjectPatch, db: Session = Depends(get_db)) -> dict:
    obj = db.get(BuildingObject, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="object not found")
    if body.name is not None:
        obj.name = body.name
    if body.city is not None:
        obj.city = body.city
    if body.notes is not None:
        obj.notes = body.notes
    db.commit()
    return {"ok": True}


@router.delete("/objects/{object_id}", status_code=204)
def delete_object(object_id: int, db: Session = Depends(get_db)) -> Response:
    obj = db.get(BuildingObject, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="object not found")
    db.query(Estimate).filter_by(object_id=object_id).update({"object_id": None})
    db.delete(obj)
    db.commit()
    return Response(status_code=204)
```

- [ ] **Step 4: Запустить весь набор.** Run: `.venv/bin/python -m pytest -q` (зелёное; объектные тесты добавились).
- [ ] **Step 5: Коммит**
```bash
git add backend/app/schemas.py backend/app/api/routes.py backend/tests/test_objects_api.py
git commit -m "feat(api): CRUD объектов строительства"
```

---

## Task 5: Концепт-эндпоинт + создание сметы из объекта + object_id в деталях сметы

**Files:** Modify `backend/app/api/routes.py`; Test `backend/tests/test_objects_api.py`

- [ ] **Step 1: Дописать падающие тесты** в `backend/tests/test_objects_api.py`:
```python
def test_concept_and_estimate_from_object():
    oid = client.post("/api/objects", json={
        "name": "Дом", "city": "Алматы", "lat": 43.24, "lon": 76.9, "polygon": POLY}).json()["id"]
    concept = client.get(f"/api/objects/{oid}/concept", params={"object_type": "Жилой дом"}).json()
    assert concept["building_length"] > 0 and concept["floors"] == 9
    assert concept["city"] == "Алматы"

    r = client.post(f"/api/objects/{oid}/estimate", json=concept)
    assert r.status_code == 200
    eid = r.json()["estimate_id"]
    full = client.get(f"/api/estimates/{eid}").json()
    assert full["object_id"] == oid
    cv = full["current_version"]
    assert cv is not None  # смета сразу рассчитана из концепта
    assert cv["input"]["building_length"] == concept["building_length"]
    # объект показывает привязанную смету
    assert any(e["id"] == eid for e in client.get(f"/api/objects/{oid}").json()["estimates"])


def test_deleting_object_keeps_estimate_and_nulls_link():
    oid = client.post("/api/objects", json={
        "name": "X", "city": "Алматы", "lat": 43.24, "lon": 76.9, "polygon": POLY}).json()["id"]
    eid = client.post(f"/api/objects/{oid}/estimate").json()["estimate_id"]   # body=None → дефолтный концепт
    assert client.delete(f"/api/objects/{oid}").status_code == 204
    full = client.get(f"/api/estimates/{eid}").json()
    assert full["object_id"] is None              # связь обнулена
    assert full["current_version"] is not None    # смета осталась рассчитанной
```

- [ ] **Step 2: Запустить — упадёт.** Run: `.venv/bin/python -m pytest tests/test_objects_api.py::test_concept_and_estimate_from_object -q`

- [ ] **Step 3a: Эндпоинты концепта и сметы** — в `backend/app/api/routes.py` добавить (после `delete_object`):
```python
def _object_dims(obj: BuildingObject) -> tuple[float, float]:
    if obj.polygon:
        return bbox_dims_m(obj.polygon)
    side = math.sqrt(obj.area_m2) if obj.area_m2 > 0 else 30.0
    return side, side


@router.get("/objects/{object_id}/concept")
def object_concept(object_id: int, object_type: str = "Жилой дом",
                   floors: int | None = None, db: Session = Depends(get_db)) -> dict:
    obj = db.get(BuildingObject, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="object not found")
    length, width = _object_dims(obj)
    inp = propose_concept(obj.area_m2 or (length * width), length, width,
                          obj.city, object_type, floors)
    inp.project_name = obj.name or "Смета"
    return to_jsonable(inp)


@router.post("/objects/{object_id}/estimate")
def object_create_estimate(object_id: int, body: BuildingInput | None = Body(None),
                           db: Session = Depends(get_db)) -> dict:
    obj = db.get(BuildingObject, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="object not found")
    if body is not None:
        inp = body
    else:
        length, width = _object_dims(obj)
        inp = propose_concept(obj.area_m2 or (length * width), length, width,
                              obj.city, "Жилой дом", None)
        inp.project_name = obj.name or "Смета"
    profile = resolve_norm_profile(db, inp)
    result = build_estimate(db, inp, profile)
    est = Estimate(name=inp.project_name or obj.name, object_type=inp.object_type,
                   city=inp.city, object_id=object_id)
    db.add(est)
    db.flush()
    version = create_version(db, est, inp, result, source="initial")
    db.commit()
    return {"estimate_id": est.id, "version_number": version.version_number}
```

- [ ] **Step 3b: Вернуть object_id в деталях сметы** — в `get_estimate_full` (`routes.py`) в возвращаемый dict, в под-объект `"estimate"`, добавить поле `object_id`, и на верхнем уровне — `object_id`. Найти:
```python
    return {
        "estimate": {"id": est.id, "name": est.name, "object_type": est.object_type,
                     "city": est.city, "status": est.status},
```
заменить на:
```python
    return {
        "estimate": {"id": est.id, "name": est.name, "object_type": est.object_type,
                     "city": est.city, "status": est.status, "object_id": est.object_id},
        "object_id": est.object_id,
```

- [ ] **Step 4: Запустить весь набор.** Run: `.venv/bin/python -m pytest -q` (зелёное).
- [ ] **Step 5: Коммит**
```bash
git add backend/app/api/routes.py backend/tests/test_objects_api.py
git commit -m "feat(api): концепт + создание сметы из объекта (привязка object_id)"
```

---

## Task 6: Leaflet в index.html + навигация «Объекты» + Api-методы

**Files:** Modify `frontend/index.html`, `frontend/app.js`

- [ ] **Step 1: index.html** — в `<head>` после строки шрифтов добавить Leaflet + leaflet-draw (CDN):
```html
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css">
  <script defer src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script defer src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>
```
И в `<nav>` после ссылки «Сметы» добавить ссылку «Объекты»:
```html
    <a class="link" data-nav="#/objects" href="#/objects">Объекты</a>
```
(`app.js` подключён в конце `<body>` без `defer` — Leaflet с `defer` загрузится раньше DOMContentLoaded-логики маршрутизатора по hashchange; первый рендер карты происходит после клика по ссылке, Leaflet к тому моменту готов.)

- [ ] **Step 2: Api-методы** — в `app.js`, в объект `Api`, после `suggestPrices: ...` добавить:
```javascript
  listObjects: () => api("GET", "/objects"),
  createObject: (body) => api("POST", "/objects", body),
  getObject: (id) => api("GET", `/objects/${id}`),
  patchObject: (id, patch) => api("PATCH", `/objects/${id}`, patch),
  deleteObject: (id) => api("DELETE", `/objects/${id}`),
  objectConcept: (id, object_type, floors) =>
    api("GET", `/objects/${id}/concept?object_type=${encodeURIComponent(object_type)}` +
      (floors ? `&floors=${floors}` : "")),
  objectCreateEstimate: (id, input) => api("POST", `/objects/${id}/estimate`, input),
```

- [ ] **Step 3: Роутер** — в `app.js` в `parseRoute()` перед `if (h.startsWith("/settings"))` добавить:
```javascript
  const mo = h.match(/^\/object\/(\d+)/);
  if (mo) return { name: "object", id: Number(mo[1]) };
  if (h.startsWith("/objects")) return { name: "objects" };
```
В `render()` в try-блоке добавить ветки:
```javascript
    else if (route.name === "objects") await viewObjects();
    else if (route.name === "object") await viewObject(route.id);
```
В `setActiveNav(route)` заменить вычисление `target` на учёт объектов:
```javascript
  const target = route.name === "settings" ? "#/settings"
    : (route.name === "objects" || route.name === "object") ? "#/objects" : "#/";
```

- [ ] **Step 4: Проверка** — `node --check frontend/app.js` → OK; перезапустить сервер и `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/` → 200; страница содержит ссылку «Объекты» (`curl -s http://127.0.0.1:8000/ | grep -c '#/objects'` → ≥1).
- [ ] **Step 5: Коммит**
```bash
git add frontend/index.html frontend/app.js
git commit -m "feat(frontend): Leaflet CDN, навигация и Api для объектов"
```

---

## Task 7: Вид «Объекты» — карта + рисование участка + список

**Files:** Modify `frontend/app.js`, `frontend/styles.css`

- [ ] **Step 1: CSS** — в `frontend/styles.css` добавить в конец:
```css
.map { height: 460px; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; margin-bottom: 16px; }
.map-mini { height: 240px; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.obj-form { display: flex; gap: 10px; align-items: flex-end; flex-wrap: wrap; margin: 12px 0; }
.obj-form .field { margin: 0; min-width: 160px; }
.concept-panel { border: 1px solid var(--line); border-radius: 12px; padding: 16px; margin: 14px 0; background: var(--surface); }
```

- [ ] **Step 2: Реализация вида** — в `app.js` добавить (рядом с другими view-функциями):
```javascript
const CITY_CENTER = { "Алматы": [43.238, 76.889], "Астана": [51.128, 71.430] };

function baseLayers() {
  const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "© OpenStreetMap" });
  const sat = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "© Esri" });
  return { "Схема": osm, "Спутник": sat };
}

let DRAWN = null; // {polygon, lat, lon, area_hint}

async function viewObjects() {
  APP().innerHTML = `
    <div class="page">
      <div class="page-head"><h1 class="title">Объекты</h1>
        <select id="citySel" class="ver-select" style="margin-left:auto;width:160px">
          <option>Алматы</option><option>Астана</option></select></div>
      <div class="subtitle">Нарисуйте контур участка на карте (инструмент «прямоугольник»), затем создайте объект.</div>
      <div id="map" class="map"></div>
      <div id="objForm"></div>
      <div id="objList"></div>
    </div>`;
  const layers = baseLayers();
  const map = L.map("map", { layers: [layers["Схема"]] }).setView(CITY_CENTER["Алматы"], 12);
  L.control.layers(layers).addTo(map);
  const drawn = new L.FeatureGroup().addTo(map);
  map.addControl(new L.Control.Draw({
    draw: { polygon: false, polyline: false, circle: false, marker: false,
            circlemarker: false, rectangle: {} },
    edit: { featureGroup: drawn, edit: false, remove: true },
  }));
  map.on(L.Draw.Event.CREATED, (e) => {
    drawn.clearLayers(); drawn.addLayer(e.layer);
    const gj = e.layer.toGeoJSON().geometry;       // Polygon
    const c = e.layer.getBounds().getCenter();
    DRAWN = { polygon: gj, lat: c.lat, lon: c.lng };
    renderObjForm();
  });
  document.getElementById("citySel").addEventListener("change", (ev) =>
    map.setView(CITY_CENTER[ev.target.value] || CITY_CENTER["Алматы"], 12));
  renderObjForm();
  await drawObjList();
}

function renderObjForm() {
  const el = document.getElementById("objForm");
  if (!DRAWN) { el.innerHTML = `<div class="hint">Участок ещё не нарисован.</div>`; return; }
  el.innerHTML = `<div class="obj-form">
    <div class="field"><label>Название</label><input id="objName" type="text" value="Новый объект"></div>
    <div class="field"><label>Город</label><select id="objCity"><option>Алматы</option><option>Астана</option></select></div>
    <button class="btn primary" id="objSave">Создать объект</button>
    <span class="hint">центр: ${DRAWN.lat.toFixed(5)}, ${DRAWN.lon.toFixed(5)}</span></div>`;
  document.getElementById("objCity").value = document.getElementById("citySel").value;
  document.getElementById("objSave").addEventListener("click", async () => {
    const { id } = await Api.createObject({
      name: document.getElementById("objName").value,
      city: document.getElementById("objCity").value,
      lat: DRAWN.lat, lon: DRAWN.lon, polygon: DRAWN.polygon });
    DRAWN = null;
    toast("Объект создан");
    location.hash = `#/object/${id}`;
  });
}

async function drawObjList() {
  const items = await Api.listObjects();
  const el = document.getElementById("objList");
  if (!items.length) { el.innerHTML = `<div class="empty">Объектов пока нет.</div>`; return; }
  el.innerHTML = `<div class="list">` + items.map((o) => `<div class="row" data-id="${o.id}">
    <div class="code">№ ${o.id}</div>
    <div class="main"><div class="name">${escapeHtml(o.name)}</div>
      <div class="meta">${escapeHtml(o.city)} · ${money(o.area_m2)} м² · смет: ${o.estimate_count}</div></div>
    <div class="status">${statusBadge(o.status === "selected" ? "calculated" : "draft")}</div>
    <button class="del" data-del="${o.id}" title="Удалить">✕</button></div>`).join("") + `</div>`;
  el.querySelectorAll(".row").forEach((r) => r.addEventListener("click", (ev) => {
    if (ev.target.dataset.del) return;
    location.hash = `#/object/${r.dataset.id}`;
  }));
  el.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    if (!confirm("Удалить объект? Привязанные сметы останутся.")) return;
    await Api.deleteObject(b.dataset.del); toast("Объект удалён"); drawObjList();
  }));
}
```

- [ ] **Step 3: Проверка** — `node --check frontend/app.js` → OK; перезапустить сервер; открыть `#/objects` в браузере — карта рендерится, рисование прямоугольника даёт форму. (Авто-смоук: `curl -s http://127.0.0.1:8000/app.js | grep -c 'function viewObjects'` → 1.)
- [ ] **Step 4: Коммит**
```bash
git add frontend/app.js frontend/styles.css
git commit -m "feat(frontend): вид «Объекты» — карта, рисование участка, список"
```

---

## Task 8: Карточка объекта — мини-карта + концепт + создание сметы

**Files:** Modify `frontend/app.js`

- [ ] **Step 1: Реализация** — в `app.js` добавить:
```javascript
async function viewObject(id) {
  const data = await Api.getObject(id);
  const o = data.object;
  APP().innerHTML = `
    <div class="page">
      <div class="breadcrumb"><a href="#/objects">Объекты</a> / ${escapeHtml(o.name)}</div>
      <div class="title-row"><input class="title-edit" id="objTitle" value="${escapeAttr(o.name)}">
        ${statusBadge(o.status === "selected" ? "calculated" : "draft")}</div>
      <div class="sub-mono">№ ${o.id} · ${escapeHtml(o.city)} · ${money(o.area_m2)} м²</div>
      <div class="detail"><div class="left">
        <div id="omap" class="map-mini"></div>
        <div id="conceptBox"></div>
        <div class="card"><h3>Сметы объекта</h3><div id="objEsts"></div></div>
      </div></div>
    </div>`;
  // карта с контуром
  const layers = baseLayers();
  const map = L.map("omap", { layers: [layers["Спутник"]] }).setView([o.lat, o.lon], 16);
  L.control.layers(layers).addTo(map);
  if (data.polygon) {
    const gj = L.geoJSON(data.polygon, { style: { color: "#2C5BA8", weight: 2 } }).addTo(map);
    map.fitBounds(gj.getBounds(), { padding: [20, 20] });
  } else { L.marker([o.lat, o.lon]).addTo(map); }

  document.getElementById("objTitle").addEventListener("change", async (ev) => {
    await Api.patchObject(id, { name: ev.target.value }); toast("Сохранено");
  });

  // список смет объекта
  const estsEl = document.getElementById("objEsts");
  estsEl.innerHTML = data.estimates.length
    ? data.estimates.map((e) => `<div class="row" data-eid="${e.id}">
        <div class="main"><div class="name">${escapeHtml(e.name)}</div></div>
        <div class="amount"><div class="total">${e.status === "calculated" ? money(e.total) + " ₸" : "—"}</div></div>
      </div>`).join("")
    : `<div class="hint">Смет ещё нет — создайте из концепта ниже.</div>`;
  estsEl.querySelectorAll("[data-eid]").forEach((r) =>
    r.addEventListener("click", () => { location.hash = `#/estimate/${r.dataset.eid}`; }));

  await renderConcept(id, o.city);
}

async function renderConcept(id, city) {
  const box = document.getElementById("conceptBox");
  box.innerHTML = `<div class="concept-panel"><h3>Концепт здания</h3>
    <div class="obj-form">
      <div class="field"><label>Тип объекта</label><select id="cType">
        <option>Жилой дом</option><option>Общественное здание</option><option>Промышленное здание</option></select></div>
      <button class="btn" id="cReload">Предложить</button>
    </div>
    <div id="cFields" class="hint">Нажмите «Предложить», чтобы система рассчитала параметры под участок.</div>
    <div class="row-actions"><button class="btn accent" id="cToEstimate" disabled>Создать смету</button></div>
  </div>`;
  let concept = null;
  const load = async () => {
    concept = await Api.objectConcept(id, document.getElementById("cType").value);
    document.getElementById("cFields").innerHTML = `<div class="grid">
      ${cField("Этажность", "floors", concept.floors)}
      ${cField("Габарит длина, м", "building_length", concept.building_length)}
      ${cField("Габарит ширина, м", "building_width", concept.building_width)}
      ${cField("Общая площадь, м²", "total_area", concept.total_area)}
    </div>`;
    document.getElementById("cToEstimate").disabled = false;
  };
  document.getElementById("cReload").addEventListener("click", load);
  document.getElementById("cToEstimate").addEventListener("click", async () => {
    document.querySelectorAll("#cFields [data-ck]").forEach((el) => {
      concept[el.dataset.ck] = Number(el.value || 0);
    });
    const { estimate_id } = await Api.objectCreateEstimate(id, concept);
    toast("Смета создана из концепта");
    location.hash = `#/estimate/${estimate_id}`;
  });
  await load();
}
function cField(label, key, val) {
  return `<div class="field"><label>${label}</label>
    <input type="number" step="0.1" data-ck="${key}" value="${escapeAttr(val)}"></div>`;
}
```

- [ ] **Step 2: Проверка** — `node --check frontend/app.js` → OK; перезапустить сервер; открыть карточку объекта — мини-карта с контуром, «Предложить» заполняет поля, «Создать смету» уводит на расчёт. (`curl -s http://127.0.0.1:8000/app.js | grep -c 'function viewObject\b'` → 1.)
- [ ] **Step 3: Коммит**
```bash
git add frontend/app.js
git commit -m "feat(frontend): карточка объекта — мини-карта, концепт, создание сметы"
```

---

## Task 9: Бейдж объекта в карточке сметы

**Files:** Modify `frontend/app.js`

- [ ] **Step 1: Реализация** — в `viewDetail(id)` (`app.js`), в шапке карточки сметы, под `.sub-mono`, добавить ссылку на объект, если он есть. Найти строку:
```javascript
      <div class="sub-mono">№ ${id} · ${escapeHtml((inp && inp.city) || data.estimate.city || "—")}</div>
```
заменить на:
```javascript
      <div class="sub-mono">№ ${id} · ${escapeHtml((inp && inp.city) || data.estimate.city || "—")}${
        data.object_id ? ` · <a href="#/object/${data.object_id}" style="color:var(--accent)">Объект №${data.object_id}</a>` : ""}</div>
```

- [ ] **Step 2: Проверка** — `node --check frontend/app.js` → OK; смета, созданная из объекта, показывает ссылку «Объект №…», ведущую на карточку.
- [ ] **Step 3: Коммит**
```bash
git add frontend/app.js
git commit -m "feat(frontend): ссылка на объект в карточке сметы"
```

---

## Definition of Done (SP1)
- Таблица `building_objects` + `Estimate.object_id` (миграция-guard на старой БД); весь набор тестов зелёный.
- `geo` и `concept` покрыты unit-тестами; CRUD объектов + концепт + создание сметы — API-тестами.
- Фронт: вид «Объекты» (карта OSM/спутник, рисование участка, список), карточка объекта (мини-карта с контуром, панель концепта, создание сметы), ссылка на объект в смете.
- Создание сметы из объекта даёт **сразу рассчитанную ресурсную смету** с засеянными из концепта габаритом/этажностью и `object_id`.
- Сметы без объекта работают как прежде (регрессия зелёная).
