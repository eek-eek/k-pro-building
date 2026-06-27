from app.norms.registry import SEED_DOCUMENTS


def test_no_known_broken_perechen_urls():
    # старые ссылки ksm.kz/egfntd/ntdgo/kds/4.php и 5.php были битыми (404)
    bad = [code for code, _t, _dt, url, _ot in SEED_DOCUMENTS
           if "ntdgo/kds/4.php" in url or "ntdgo/kds/5.php" in url]
    assert not bad, f"снова битые «перечень»-ссылки у: {bad}"


def test_all_docs_have_http_url():
    assert all(url.startswith("http") for _c, _t, _dt, url, _ot in SEED_DOCUMENTS)
