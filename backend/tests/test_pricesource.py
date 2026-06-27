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
    html = "350 000 ₸ 360 000 ₸ 370 000 ₸ 999 ₸"
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
