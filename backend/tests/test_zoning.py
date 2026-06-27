from app.zoning.heuristics import use_mismatch_warning


def test_warns_on_greening_plot_for_building():
    w = use_mismatch_warning("для благоустройства и озеленения территории", "Жилой дом")
    assert w and "назначени" in w.lower()


def test_no_warning_when_purpose_allows_construction():
    assert use_mismatch_warning("для строительства жилого комплекса", "Жилой дом") is None


def test_no_warning_when_purpose_unknown_or_empty():
    assert use_mismatch_warning("", "Жилой дом") is None
