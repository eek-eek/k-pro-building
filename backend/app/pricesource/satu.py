"""Satu.kz: цены материалов из категорий (HTML-парсинг → медиана).

Только материалы; розничные цены; парсер изолирован — при сети/пустом парсе/битой
разметке откат на курируемую цену (расчёт никогда не падает). Слаги категорий
best-effort (rebar проверен); неверный URL → курируемая цена."""
from __future__ import annotations

import re
import statistics
from typing import Callable, Optional

from .base import PriceQuote
from .curated import CuratedSource

SATU_CATEGORIES: dict[str, str] = {
    "rebar_a500": "https://satu.kz/Armatura-stalnaya.html",
    "concrete_b25": "https://satu.kz/Beton-tovarnyj.html",
    "aerated_block": "https://satu.kz/Gazoblok.html",
    "mineral_wool_w": "https://satu.kz/Mineralnaya-vata.html",
    "mineral_wool_r": "https://satu.kz/Mineralnaya-vata.html",
    "xps": "https://satu.kz/Ekstrudirovannyj-penopolistirol.html",
}

# Город сметы → регион Satu (cps-region-id). Пусто = национальная выдача.
# Статичный HTML Satu region-id точно не подтверждён → пока национально + город в
# подписи; при появлении проверенных id выдача сузится до города (Алматы→Алматы).
SATU_CITY_REGION: dict[str, str] = {
    "Алматы": "",
    "Астана": "",
    "Шымкент": "",
}

_PRICE_RE = re.compile(r"(\d[\d\s ]{2,})\s*(?:₸|тг|тенге)", re.IGNORECASE)

# Доверяем Satu только при достаточной выборке после фильтра шума; иначе откат на
# курируемую цену (статичный HTML Satu отдаёт мало цен — единичные значения шумны).
MIN_SAMPLES = 3


def parse_prices(html: str) -> list[float]:
    out: list[float] = []
    for m in _PRICE_RE.finditer(html or ""):
        digits = re.sub(r"[\s ]", "", m.group(1))
        try:
            v = float(digits)
        except ValueError:
            continue
        if v > 0:
            out.append(v)
    return out


class SatuSource:
    name = "satu"

    def __init__(self, fetch: Optional[Callable[[str], str]] = None):
        self._fetch = fetch or self._http_fetch
        self._cache: dict[str, str] = {}
        self._curated = CuratedSource()

    def _http_fetch(self, url: str) -> str:
        import urllib.request
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SmetaBot/1.0)"}
        region = getattr(self, "_region", None)
        if region:                       # ограничить выдачу регионом города (Satu cookie)
            headers["Cookie"] = f"cps-region-id={region}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8", "ignore")

    def quote_materials(self, codes: list[str], city: str | None = None) -> dict[str, PriceQuote]:
        curated = self._curated.quote_materials(codes, city)
        out: dict[str, PriceQuote] = {}
        city_label = city or "РК"
        self._region = SATU_CITY_REGION.get(city or "")   # None = национально
        for c in codes:
            anchor = curated[c].price if c in curated else None
            url = SATU_CATEGORIES.get(c)
            quote: Optional[PriceQuote] = None
            if url and anchor:
                try:
                    key = f"{city or '*'}|{url}"            # кэш отдельно по городу
                    html = self._cache.get(key)
                    if html is None:
                        html = self._fetch(url)
                        self._cache[key] = html
                    prices = [p for p in parse_prices(html) if 0.2 * anchor <= p <= 5 * anchor]
                    if len(prices) >= MIN_SAMPLES:
                        med = round(statistics.median(prices))
                        quote = PriceQuote(code=c, price=med, source="satu",
                                           note=f"медиана {len(prices)} предложений Satu, {city_label} (розница)")
                except Exception:
                    quote = None
            if quote is None and c in curated:
                quote = curated[c]
                if url:
                    quote.note = "Satu недоступно — курируемая цена"
            if quote is not None:
                out[c] = quote
        return out
