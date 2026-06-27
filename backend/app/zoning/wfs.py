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
                props = (plot or {}).get("properties", {})
                return ZoneVerdict(status="restricted", zone="водоохранная зона",
                                   land_use=props.get("tsn_ru", ""),
                                   kad_nomer=props.get("kad_nomer", ""),
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
