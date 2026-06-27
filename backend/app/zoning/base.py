"""Контракт провайдера проверки зоны участка."""
from __future__ import annotations

from ..schemas import ZoneVerdict


class ZoningProvider:
    name: str = "base"

    def check(self, lat: float, lon: float, object_type: str = "",
              city: str = "") -> ZoneVerdict:  # pragma: no cover
        raise NotImplementedError
