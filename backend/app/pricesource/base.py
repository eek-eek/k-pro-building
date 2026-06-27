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
    def quote_materials(self, codes: list[str]) -> dict[str, PriceQuote]: ...
