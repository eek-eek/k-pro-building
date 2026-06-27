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
