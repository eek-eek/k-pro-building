from app.zoning.heuristics import use_mismatch_warning
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


# Водоохранная фича возвращена WFS по bbox, но её полигон точку НЕ накрывает
# (крупная зона: bounding box перекрывает запрос, но участок вне зоны).
_WATER_FAR = {"features": [{
    "geometry": {"type": "Polygon", "coordinates": [[
        [77.000, 43.300], [77.002, 43.300], [77.002, 43.302], [77.000, 43.302], [77.000, 43.300]]]},
    "properties": {}}]}


def test_verdict_allowed_when_water_feature_near_but_not_containing(monkeypatch):
    _fake_wfs(monkeypatch, {"openmap:land_plots": _PLOT,
                            "geonode:almaty_waterprotectionzone": _WATER_FAR})
    v = get_zoning_provider().check(*ALMATY, object_type="Жилой дом", city="Алматы")
    assert v.status == "allowed"  # точка вне водоохранного полигона → не ограничено


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


def test_warns_on_greening_plot_for_building():
    w = use_mismatch_warning("для благоустройства и озеленения территории", "Жилой дом")
    assert w and "назначени" in w.lower()


def test_no_warning_when_purpose_allows_construction():
    assert use_mismatch_warning("для строительства жилого комплекса", "Жилой дом") is None


def test_no_warning_when_purpose_unknown_or_empty():
    assert use_mismatch_warning("", "Жилой дом") is None
