import pytest
from app.chat.editor import merge_and_recompute, ChatEditError
from app.schemas import BuildingInput, EstimateLine, EstimateResult, EstimateTotals


def _line(no, qty, mat):
    return EstimateLine(no=no, section="Земляные работы", title="t", unit="м³",
                        quantity=qty, material_price=mat, total=round(qty * mat))


def _prev():
    lines = [_line("2.1", 10, 100), _line("2.2", 5, 200)]
    return EstimateResult(project_name="p", city="c", object_type="o", lines=lines,
                          section_totals={"Земляные работы": 2000},
                          totals=EstimateTotals(grand_total=2000), warnings=["w0"])


def test_merge_applies_partial_line_update_and_recomputes():
    prev = _prev()
    inp = BuildingInput(overhead_pct=0, contingency_pct=0, vat_pct=0)
    data = {"reply": "ок", "lines": [{"no": "2.1", "quantity": 20}, {"no": "2.2"}],
            "warnings_add": ["проверьте объём"]}
    result, reply = merge_and_recompute(prev, inp, data)
    assert reply == "ок"
    l21 = next(l for l in result.lines if l.no == "2.1")
    assert l21.quantity == 20
    assert l21.total == 2000  # 20 * 100, recomputed server-side
    assert l21.title == "t"   # preserved from prev (partial update merged)
    assert result.totals.grand_total == 3000  # 2000 + 1000
    assert "проверьте объём" in result.warnings


def test_merge_rejects_empty_lines():
    prev = _prev()
    inp = BuildingInput()
    with pytest.raises(ChatEditError):
        merge_and_recompute(prev, inp, {"reply": "x", "lines": []})


def test_merge_rejects_garbage_line():
    prev = _prev()
    inp = BuildingInput()
    with pytest.raises(ChatEditError):
        merge_and_recompute(prev, inp, {"lines": [{"no": "9.9", "quantity": "abc"}]})
