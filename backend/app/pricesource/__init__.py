"""Источники цен материалов: курируемый (по умолчанию) и Satu."""
from .base import PriceQuote, PriceSource
from .curated import CuratedSource
from .satu import SatuSource

_SOURCES = {"curated": CuratedSource, "satu": SatuSource}


def get_price_source(name: str) -> "PriceSource":
    cls = _SOURCES.get(name) or CuratedSource
    return cls()


def available_sources() -> list[dict]:
    return [
        {"name": "curated", "title": "Курируемые цены РК"},
        {"name": "satu", "title": "Satu.kz (розница, материалы)"},
    ]


__all__ = ["PriceQuote", "PriceSource", "CuratedSource", "SatuSource",
           "get_price_source", "available_sources"]
