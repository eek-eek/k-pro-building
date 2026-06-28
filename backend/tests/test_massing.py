"""Геометрия здания из массинга (набор блоков): метрики, derive, санитайз."""
from app.schemas import BuildingInput, MassingBox
from app.calc.massing import massing_metrics, sanitize_boxes
from app.calc.geometry import derive


def _boxes(*specs):
    # spec: (x, y, w, d, floors, base)
    return [MassingBox(x=x, y=y, w=w, d=d, floors=f, base=b) for (x, y, w, d, f, b) in specs]


def test_metrics_single_box():
    m = massing_metrics(_boxes((0, 0, 40, 30, 10, 0)), floor_height=3.0)
    assert m["build_area"] == 40 * 30            # 1200 застройка
    assert m["total_area"] == 40 * 30 * 10       # 12000 общая
    assert m["facade_area"] == 2 * (40 + 30) * 10 * 3.0   # 4200 фасад
    assert m["building_volume"] == 40 * 30 * 10 * 3.0
    assert m["floors"] == 10
    assert m["length"] == 40 and m["width"] == 30


def test_metrics_tower_without_ground_block_has_footprint():
    # все блоки base>0 (нет наземного) — пятно НЕ обнуляется (union по проекциям)
    m = massing_metrics(_boxes((0, 0, 20, 20, 5, 3)), floor_height=3.0)
    assert m["build_area"] == 400  # иначе фундамент/кровля были бы нулевыми


def test_metrics_overlap_not_double_counted():
    # стилобат 40×30 + башня 20×20 ВНУТРИ него, оба base=0 → union пятна, не сумма
    boxes = _boxes((0, 0, 40, 30, 3, 0), (5, 5, 20, 20, 10, 0))
    m = massing_metrics(boxes, floor_height=3.0)
    assert m["build_area"] == 40 * 30  # 1200, не 1200+400


def test_metrics_guards_nonpositive_floor_height():
    m = massing_metrics(_boxes((0, 0, 10, 10, 2, 0)), floor_height=-3.0)
    assert m["facade_area"] > 0 and m["building_volume"] > 0 and m["total_height"] > 0


def test_metrics_podium_plus_tower():
    # стилобат 40×30×3 (base 0) + башня 20×18×16 (base 3)
    boxes = _boxes((0, 0, 40, 30, 3, 0), (5, 5, 20, 18, 16, 3))
    m = massing_metrics(boxes, floor_height=3.0)
    assert m["build_area"] == 40 * 30            # застройка — только наземные (base=0)
    assert m["total_area"] == 40 * 30 * 3 + 20 * 18 * 16
    assert m["floors"] == 3 + 16                 # max(base+floors) = 19
    assert m["length"] == 40 and m["width"] == 30


def test_derive_uses_massing_when_present():
    inp = BuildingInput(object_type="Жилой дом", floor_height=3.0,
                        massing=_boxes((0, 0, 40, 30, 10, 0)))
    geo = derive(inp)
    assert geo.build_area == 1200
    assert geo.total_area == 12000
    assert geo.facade_area == 4200
    assert geo.floors == 10


def test_derive_falls_back_without_massing():
    inp = BuildingInput(object_type="Жилой дом", building_length=10, building_width=15,
                        floors=3, form="box")  # massing=None
    geo = derive(inp)
    assert geo.build_area == 150  # старая формула 10×15×1.0


def test_sanitize_drops_invalid_and_caps_count():
    raw = [{"x": 0, "y": 0, "w": -5, "d": 30, "floors": 10, "base": 0}]  # w<=0 → отброшен
    raw += [{"x": 0, "y": 0, "w": 10, "d": 10, "floors": 3, "base": 0}] * 30  # >16 → кап
    boxes, notes = sanitize_boxes(raw)
    assert all(b.w > 0 and b.d > 0 for b in boxes)
    assert len(boxes) <= 16
    assert notes  # были правки → есть заметки


def test_sanitize_clamps_dims_and_floors():
    boxes, _ = sanitize_boxes([{"x": 0, "y": 0, "w": 9999, "d": 10, "floors": 999, "base": 0}])
    assert boxes[0].w <= 500       # габарит зажат
    assert boxes[0].floors <= 200  # этажи зажаты


def test_sanitize_normalizes_base_to_ground():
    # единственный блок с base>0 (парящее здание) → опускаем на грунт
    boxes, notes = sanitize_boxes([{"x": 0, "y": 0, "w": 20, "d": 20, "floors": 5, "base": 3}])
    assert boxes[0].base == 0
    assert any("грунт" in n for n in notes)


def test_sanitize_floors_zero_is_noted():
    # floors=0 → 1, но с заметкой (раньше молча превращалось без отметки)
    boxes, notes = sanitize_boxes([{"x": 0, "y": 0, "w": 10, "d": 10, "floors": 0, "base": 0}])
    assert boxes[0].floors == 1 and any("этажност" in n for n in notes)


def test_estimate_uses_massing_geometry(db):
    from app.calc.estimate import build_estimate
    from app.norms.resolver import resolve_norm_profile
    inp = BuildingInput(object_type="Жилой дом", demo_mode=True, use_search=False,
                        floor_height=3.0, massing=_boxes((0, 0, 40, 30, 10, 0)))
    profile = resolve_norm_profile(db, inp)
    res = build_estimate(db, inp, profile)
    assert inp.total_area == 12000   # площадь синхронизирована из массинга
    assert res.totals.grand_total > 0
    assert not any("физический максимум" in w for w in res.warnings)  # контроля площади нет
