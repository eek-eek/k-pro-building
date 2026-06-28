"""Формы здания и их влияние на геометрию сметы.

Каждая форма задаёт два ориентировочных коэффициента к габариту-bounding box:
- footprint — доля застройки/кровли/фундамента (двор/башня → меньше);
- facade   — относительная длина наружных стен/фасада (двор → больше; купол → меньше).

Брусок нейтрален (1.0/1.0): сметы без выбора формы считаются как прежде.
Значения приближённые — инструмент предварительный."""
from __future__ import annotations

# key → label, footprint_factor, facade_factor
FORMS: dict[str, dict] = {
    "box":      {"label": "Брусок",              "footprint": 1.00, "facade": 1.00},
    "tower":    {"label": "Башня",               "footprint": 0.70, "facade": 1.15},
    "court":    {"label": "L / П-двор",          "footprint": 0.72, "facade": 1.30},
    "stepped":  {"label": "Ступенчатое",         "footprint": 0.90, "facade": 1.10},
    "dome":     {"label": "Купол (hi-fi)",       "footprint": 0.85, "facade": 0.85},
    "gable":    {"label": "Дом со скатной крышей", "footprint": 1.00, "facade": 1.05},
    "podium":   {"label": "Стилобат + башня",    "footprint": 0.85, "facade": 1.18},
    "cylinder": {"label": "Цилиндр",             "footprint": 0.80, "facade": 0.80},
}
DEFAULT_FORM = "box"


def _form(form: str) -> dict:
    return FORMS.get(form, FORMS[DEFAULT_FORM])


def footprint_factor(form: str) -> float:
    return _form(form)["footprint"]


def facade_factor(form: str) -> float:
    return _form(form)["facade"]
