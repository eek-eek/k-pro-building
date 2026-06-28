"""Адаптер источника цен материалов."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class PriceQuote:
    code: str
    price: float
    source: str        # "curated" | "satu"
    note: str = ""


class PriceSource(Protocol):
    name: str
    # city — город сметы; источник может ограничить выборку этим городом.
    def quote_materials(self, codes: list[str], city: str | None = None) -> dict[str, PriceQuote]: ...
