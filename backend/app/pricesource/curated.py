"""Курируемый источник: цены материалов из каталога ресурсов."""
from __future__ import annotations

from .base import PriceQuote
from ..calc.resource_catalog import COMPOSITIONS


def curated_material_prices() -> dict[str, float]:
    out: dict[str, float] = {}
    for specs in COMPOSITIONS.values():
        for s in specs:
            if s.kind == "material":
                out.setdefault(s.code, s.price)
    return out


class CuratedSource:
    name = "curated"

    def quote_materials(self, codes: list[str], city: str | None = None) -> dict[str, PriceQuote]:
        # Курируемые цены национальные — город не влияет (параметр для общего контракта).
        prices = curated_material_prices()
        return {
            c: PriceQuote(code=c, price=prices[c], source="curated", note="курируемая цена РК")
            for c in codes if c in prices
        }
