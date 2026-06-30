from app.norms.registry import SEED_DOCUMENTS, documents_for


def test_construction_code_registered_for_every_object_type():
    # Строительный кодекс №253-VIII — рамочный, применим к любому типу объекта.
    for ot in ("Жилой дом", "Офис", "Производственный объект", "Реконструкция / ремонт"):
        codes = [c for c, *_ in documents_for(ot)]
        assert any("Строительный кодекс" in c for c in codes), ot
    # и официальная ссылка adilet на месте
    kodeks = [d for d in SEED_DOCUMENTS if "Строительный кодекс" in d[0]]
    assert kodeks and "adilet.zan.kz/rus/docs/K2600000253" in kodeks[0][3]


def test_no_known_broken_perechen_urls():
    # старые ссылки ksm.kz/egfntd/ntdgo/kds/4.php и 5.php были битыми (404)
    bad = [code for code, _t, _dt, url, _ot in SEED_DOCUMENTS
           if "ntdgo/kds/4.php" in url or "ntdgo/kds/5.php" in url]
    assert not bad, f"снова битые «перечень»-ссылки у: {bad}"


def test_all_docs_have_http_url():
    assert all(url.startswith("http") for _c, _t, _dt, url, _ot in SEED_DOCUMENTS)
