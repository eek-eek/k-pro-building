from app.calc import build_estimate
from app.calc.forms import FORMS, DEFAULT_FORM, footprint_factor, facade_factor
from app.calc.geometry import derive
from app.norms import resolve_norm_profile
from app.schemas import BuildingInput


def _inp(form: str) -> BuildingInput:
    return BuildingInput(building_length=40, building_width=25, floors=9, floor_height=3,
                         total_area=40 * 25 * 9, form=form, demo_mode=True, use_search=False)


def test_geometry_scales_with_form():
    box = derive(_inp("box"))
    court = derive(_inp("court"))
    tower = derive(_inp("tower"))
    assert court.build_area < box.build_area     # двор — меньше застройки/кровли
    assert court.facade_area > box.facade_area   # двор — больше фасада
    assert tower.build_area < box.build_area     # башня — меньше фундамента


def test_estimate_total_differs_by_form(db):
    def total(form):
        inp = _inp(form)
        return build_estimate(db, inp, resolve_norm_profile(db, inp)).totals.grand_total
    box = total("box")
    assert total("court") != box       # форма реально меняет смету
    assert total("dome") != box
    assert total("box") == box         # бокс детерминирован (регрессия)


def test_default_form_is_neutral():
    assert footprint_factor(DEFAULT_FORM) == 1.0
    assert facade_factor(DEFAULT_FORM) == 1.0


def test_unknown_form_falls_back_to_neutral():
    assert footprint_factor("zzz") == 1.0
    assert facade_factor("zzz") == 1.0


def test_court_more_facade_less_footprint():
    assert facade_factor("court") > 1.0
    assert footprint_factor("court") < 1.0


def test_all_forms_have_label_and_positive_factors():
    for key, f in FORMS.items():
        assert f["label"]
        assert f["footprint"] > 0 and f["facade"] > 0
