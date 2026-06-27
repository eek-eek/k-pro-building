# v0.3 План 4 — Источник цен материалов (адаптер + Satu) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development или executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Адаптер источника цен материалов: курируемый по умолчанию + опциональный Satu-провайдер (парсинг категорий → медиана, фильтр шума по курируемому анкору, кэш, мягкая деградация). Эндпоинты предложений; кнопка на фронте.

**Architecture:** Новый пакет `app/pricesource/` с `PriceQuote`, `CuratedSource`, `SatuSource`. Только материалы (труд/машины — всегда курируемые). Satu-парсер изолирован: при сети/пустом парсе/битой разметке → откат на курируемую цену, расчёт никогда не падает. Фильтр шума: оставляем цены в полосе [0.2×, 5×] от курируемой. Эндпоинт возвращает предложения для ревью; применение — обычной правкой ресурсов через существующий `manual-edit`.

**Tech Stack:** Python 3.11, stdlib `urllib`/`re`/`statistics`, pytest. Все команды из `backend/`, интерпретатор `.venv/bin/python`. Тесты **без реальной сети** (инъекция `fetch`).

**Контекст:** коды материальных ресурсов — из `app/calc/resource_catalog.py` (`COMPOSITIONS`, поля `ResourceSpec.code/kind/price`). Satu отдаёт цены в plain HTML на категорийных страницах (rebar проверен); поисковый URL цен НЕ отдаёт.

---

## File Structure
- Create: `backend/app/pricesource/__init__.py`, `base.py`, `curated.py`, `satu.py`
- Modify: `backend/app/schemas.py` (SuggestPricesRequest), `backend/app/api/routes.py` (2 эндпоинта)
- Test: `backend/tests/test_pricesource.py`, `backend/tests/test_pricesource_api.py`

---

## Task 1: Пакет `pricesource` (base/curated/satu) + тесты

**Files:** Create `backend/app/pricesource/{__init__,base,curated,satu}.py`; Test `backend/tests/test_pricesource.py`

- [ ] **Step 1: Падающие тесты** — создать `backend/tests/test_pricesource.py`:

```python
from app.pricesource import CuratedSource, SatuSource, available_sources
from app.pricesource.satu import parse_prices


def test_parse_prices_extracts_kzt_numbers():
    html = "<div>360 000 ₸</div><span>380 000 ₸</span> цена 295 000 тг"
    assert parse_prices(html) == [360000.0, 380000.0, 295000.0]


def test_curated_source_returns_catalog_prices():
    q = CuratedSource().quote_materials(["rebar_a500", "concrete_b25"])
    assert q["rebar_a500"].source == "curated"
    assert q["rebar_a500"].price > 0


def test_satu_median_with_injected_html():
    html = "350 000 ₸ 360 000 ₸ 370 000 ₸ 999 ₸"  # 999 — шум, отфильтруется по анкору
    src = SatuSource(fetch=lambda url: html)
    q = src.quote_materials(["rebar_a500"])
    assert q["rebar_a500"].source == "satu"
    assert q["rebar_a500"].price == 360000


def test_satu_falls_back_to_curated_on_error():
    def boom(url):
        raise RuntimeError("network down")
    q = SatuSource(fetch=boom).quote_materials(["rebar_a500"])
    assert q["rebar_a500"].source == "curated"


def test_satu_ignores_unmapped_or_nonmaterial():
    q = SatuSource(fetch=lambda url: "1 ₸").quote_materials(["steelfixer"])
    assert "steelfixer" not in q


def test_available_sources_lists_curated_and_satu():
    assert {s["name"] for s in available_sources()} == {"curated", "satu"}
```

- [ ] **Step 2: Запустить — упадёт** (`ModuleNotFoundError: app.pricesource`).
Run: `.venv/bin/python -m pytest tests/test_pricesource.py -q`

- [ ] **Step 3: Реализовать пакет**

`backend/app/pricesource/base.py`:
```python
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
```

`backend/app/pricesource/curated.py`:
```python
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

    def quote_materials(self, codes: list[str]) -> dict[str, PriceQuote]:
        prices = curated_material_prices()
        return {
            c: PriceQuote(code=c, price=prices[c], source="curated", note="курируемая цена РК")
            for c in codes if c in prices
        }
```

`backend/app/pricesource/satu.py`:
```python
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

_PRICE_RE = re.compile(r"(\d[\d\s ]{2,})\s*(?:₸|тг|тенге)", re.IGNORECASE)


def parse_prices(html: str) -> list[float]:
    out: list[float] = []
    for m in _PRICE_RE.finditer(html or ""):
        digits = re.sub(r"[\s ]", "", m.group(1))
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
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; SmetaBot/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8", "ignore")

    def quote_materials(self, codes: list[str]) -> dict[str, PriceQuote]:
        curated = self._curated.quote_materials(codes)
        out: dict[str, PriceQuote] = {}
        for c in codes:
            anchor = curated[c].price if c in curated else None
            url = SATU_CATEGORIES.get(c)
            quote: Optional[PriceQuote] = None
            if url and anchor:
                try:
                    html = self._cache.get(url)
                    if html is None:
                        html = self._fetch(url)
                        self._cache[url] = html
                    prices = [p for p in parse_prices(html) if 0.2 * anchor <= p <= 5 * anchor]
                    if prices:
                        med = round(statistics.median(prices))
                        quote = PriceQuote(code=c, price=med, source="satu",
                                           note=f"медиана {len(prices)} предложений Satu (розница)")
                except Exception:
                    quote = None
            if quote is None and c in curated:
                quote = curated[c]
                if url:
                    quote.note = "Satu недоступно — курируемая цена"
            if quote is not None:
                out[c] = quote
        return out
```

`backend/app/pricesource/__init__.py`:
```python
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
```

- [ ] **Step 4: Запустить — пройдёт.** Run: `.venv/bin/python -m pytest tests/test_pricesource.py -q` (6 passed).

- [ ] **Step 5: Коммит**
```bash
cd /Users/eek/Docs/kpro_case/mvp1/repo/k-pro-building
git add backend/app/pricesource backend/tests/test_pricesource.py
git commit -m "feat(pricesource): адаптер цен материалов — Curated + Satu (парсинг/медиана/деградация)"
```

---

## Task 2: Эндпоинты `/price-sources` и `/suggest-material-prices` + тесты

**Files:** Modify `backend/app/schemas.py`, `backend/app/api/routes.py`; Test `backend/tests/test_pricesource_api.py`

- [ ] **Step 1: Падающие тесты** — создать `backend/tests/test_pricesource_api.py`:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _calc():
    return client.post("/api/estimate/sync", json={
        "object_type": "Жилой дом", "demo_mode": True, "use_search": False}).json()["estimate_id"]


def test_price_sources_endpoint():
    names = {s["name"] for s in client.get("/api/price-sources").json()}
    assert {"curated", "satu"} <= names


def test_suggest_curated_prices():
    eid = _calc()
    r = client.post(f"/api/estimates/{eid}/suggest-material-prices", json={"source": "curated"})
    assert r.status_code == 200
    sugg = r.json()["suggestions"]
    assert sugg
    assert any(v["source"] == "curated" for v in sugg.values())


def test_suggest_on_missing_estimate_404():
    r = client.post("/api/estimates/999999/suggest-material-prices", json={"source": "curated"})
    assert r.status_code == 404
```

- [ ] **Step 2: Запустить — упадёт** (404/нет эндпоинта).
Run: `.venv/bin/python -m pytest tests/test_pricesource_api.py -q`

- [ ] **Step 3: Реализовать**

В `backend/app/schemas.py` после `class RecommendationAdd(...)` добавить:
```python
class SuggestPricesRequest(BaseModel):
    source: str = "satu"
```

В `backend/app/api/routes.py`: добавить импорт после строки `from ..norms import resolve_norm_profile`:
```python
from ..pricesource import get_price_source, available_sources
```
В блоке импорта схем добавить `SuggestPricesRequest` к списку из `..schemas`.

Добавить эндпоинты (после функции `add_recommendation`):
```python
@router.get("/price-sources")
def list_price_sources() -> list[dict]:
    return available_sources()


@router.post("/estimates/{estimate_id}/suggest-material-prices")
def suggest_material_prices(estimate_id: int, body: SuggestPricesRequest,
                            db: Session = Depends(get_db)) -> dict:
    est = db.get(Estimate, estimate_id)
    if est is None or est.current_version is None:
        raise HTTPException(status_code=404, detail="estimate not calculated")
    result = EstimateResult(**est.current_version.result)
    codes: list[str] = []
    seen: set[str] = set()
    for ln in result.lines:
        for r in (ln.resources or []):
            if r.kind == "material" and r.code not in seen:
                seen.add(r.code)
                codes.append(r.code)
    quotes = get_price_source(body.source).quote_materials(codes)
    return {
        "source": body.source,
        "suggestions": {c: {"price": q.price, "source": q.source, "note": q.note}
                        for c, q in quotes.items()},
    }
```

- [ ] **Step 4: Запустить весь набор.** Run: `.venv/bin/python -m pytest -q` (было 69; теперь 78).

- [ ] **Step 5: Коммит**
```bash
cd /Users/eek/Docs/kpro_case/mvp1/repo/k-pro-building
git add backend/app/schemas.py backend/app/api/routes.py backend/tests/test_pricesource_api.py
git commit -m "feat(api): /price-sources + /suggest-material-prices (источник цен)"
```

---

## Task 3: Фронтенд — кнопка «Цены материалов: Satu» (выполняется инлайн контроллером)

Не для субагента — контроллер реализует в `frontend/app.js`:
- `Api.suggestPrices(id, source)` → POST.
- Кнопка `Цены материалов: Satu` в `row-actions` карточки сметы → `suggestSatuPrices()`: `syncEdits()`, запрос предложений, применить `price` к ресурсам по `code` (только material), `rerenderTbody()`, тост «Применено N (Satu: M) — проверьте и сохраните». Совещательно: применяется в редактируемую таблицу, сохранение — кнопкой «Сохранить правки».

---

## Definition of Done
- `pricesource` пакет: Curated + Satu (парсинг/медиана/анкор-фильтр/кэш/деградация), 6 unit-тестов.
- Эндпоинты `/price-sources`, `/suggest-material-prices`, 3 API-теста; весь набор зелёный (78).
- Фронт: кнопка обновляет цены материалов из Satu в редактируемую таблицу для ревью и сохранения.
- Без реальной сети в тестах; при сбое Satu — курируемые цены, расчёт не падает.
