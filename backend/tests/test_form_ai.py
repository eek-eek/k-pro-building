"""ИИ-генерация формы здания с нормоконтролем (calc/form_ai)."""
from app.calc.form_ai import generate_form


class _FakeProvider:
    def __init__(self, payload):
        self._p = payload

    def extract_json(self, system, user, *, use_search=False):
        return self._p, []


def test_generate_demo_fallback(db):
    # demo-провайдер недоступен → прямоугольная форма из габаритов сметы
    base = {"building_length": 30, "building_width": 20, "floors": 5, "floor_height": 3}
    form = generate_form(db, "стеклянная башня", base)
    assert form.status == "ok"
    assert form.boxes and form.boxes[0].w == 30 and form.boxes[0].floors == 5
    assert "демо" in form.message.lower() or "недоступ" in form.message.lower()


def test_generate_parses_ai_massing(db, monkeypatch):
    payload = {"status": "ok", "message": "", "floor_height": 3.0,
               "boxes": [{"x": 0, "y": 0, "w": 40, "d": 30, "floors": 3, "base": 0},
                         {"x": 5, "y": 5, "w": 20, "d": 18, "floors": 16, "base": 3}]}
    monkeypatch.setattr("app.calc.form_ai.get_provider", lambda: _FakeProvider(payload))
    form = generate_form(db, "стилобат с башней", {"floor_height": 3})
    assert form.status == "ok" and len(form.boxes) == 2


def test_generate_rejected_passthrough(db, monkeypatch):
    payload = {"status": "rejected", "boxes": [],
               "message": "Газоблочный небоскрёб 300 этажей нереализуем конструктивно."}
    monkeypatch.setattr("app.calc.form_ai.get_provider", lambda: _FakeProvider(payload))
    form = generate_form(db, "газоблочный небоскрёб 300 этажей", {})
    assert form.status == "rejected" and not form.boxes and "нереализуем" in form.message


def test_generate_clamp_downgrades_to_adjusted(db, monkeypatch):
    # ИИ сказал ok, но габарит за пределом → серверный кламп → adjusted + объяснение
    payload = {"status": "ok", "message": "",
               "boxes": [{"x": 0, "y": 0, "w": 9999, "d": 20, "floors": 3, "base": 0}]}
    monkeypatch.setattr("app.calc.form_ai.get_provider", lambda: _FakeProvider(payload))
    form = generate_form(db, "огромный дом", {})
    assert form.status == "adjusted"
    assert form.boxes[0].w <= 500 and "Серверная проверка" in form.message


def test_generate_slenderness_flag(db, monkeypatch):
    # тонкая башня: высота/сторона >> предела → adjusted с замечанием об устойчивости
    payload = {"status": "ok", "floor_height": 3.0,
               "boxes": [{"x": 0, "y": 0, "w": 8, "d": 8, "floors": 60, "base": 0}]}
    monkeypatch.setattr("app.calc.form_ai.get_provider", lambda: _FakeProvider(payload))
    form = generate_form(db, "игла", {})
    assert form.status == "adjusted" and "устойчив" in form.message.lower()


def test_generate_clamps_floor_height(db, monkeypatch):
    # ИИ вернул мусорную высоту этажа → клампится в физический диапазон
    payload = {"status": "ok", "floor_height": -5,
               "boxes": [{"x": 0, "y": 0, "w": 20, "d": 20, "floors": 3, "base": 0}]}
    monkeypatch.setattr("app.calc.form_ai.get_provider", lambda: _FakeProvider(payload))
    form = generate_form(db, "дом", {})
    assert 2.0 <= form.floor_height <= 6.0


def test_building_form_endpoint_demo():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.post("/api/building-form/generate",
                    json={"description": "башня",
                          "base": {"building_length": 25, "building_width": 18, "floors": 8}})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok" and d["boxes"] and d["boxes"][0]["w"] == 25
