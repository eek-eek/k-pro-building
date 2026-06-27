"""Pydantic-схемы: вход, нормативный профиль, объёмы, смета, статусы."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────── Вход от заказчика ───────────────────────────
class BuildingInput(BaseModel):
    project_name: str = "Черновая смета объекта"
    city: str = "Астана / Казахстан"
    object_type: str = "Жилой дом"
    floors: int = 5
    total_area: float = 2500.0  # м²
    building_length: float = 50.0  # м
    building_width: float = 20.0  # м
    floor_height: float = 3.0  # м
    structure_type: str = "Монолитный железобетон"
    foundation_type: str = "Плита"
    finish_level: str = "Черновая"
    engineering_level: str = "Базовая"
    basement: bool = False
    parking: bool = False
    use_search: bool = True
    demo_mode: bool = False

    overhead_pct: float = 8.0
    contingency_pct: float = 5.0
    vat_pct: float = 12.0

    works: list[str] = Field(default_factory=list)
    assumptions: str = ""

    def discriminators(self) -> dict[str, str]:
        """Атрибуты, влияющие на выбор норм (без названий/процентов/цен).

        Единый источник истины для сигнатуры кэша, сопоставления правил и
        условий, под которыми правила сохраняются в БД. Значения — строки,
        чтобы корректно сравниваться с сохранёнными JSON-условиями.
        """
        return {
            "object_type": self.object_type,
            "structure_type": self.structure_type,
            "foundation_type": self.foundation_type,
            "finish_level": self.finish_level,
            "engineering_level": self.engineering_level,
            "basement": "да" if self.basement else "нет",
            "parking": "да" if self.parking else "нет",
            # регион влияет на нормы/климат (теплотехника)
            "region": self.city.split("/")[0].strip().lower(),
        }

    def signature(self) -> str:
        """Хэш профиля, влияющего на выбор норм."""
        raw = json.dumps(self.discriminators(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# ─────────────────────────── Нормативный профиль ───────────────────────────
class NormParam(BaseModel):
    """Один нормативный коэффициент с провенансом."""

    category: str
    value: float
    unit: str = ""
    source: str = "default"  # seed|llm|document|default
    confidence: float = 0.5
    document_code: Optional[str] = None
    note: str = ""
    needs_review: bool = False


class NormSource(BaseModel):
    code: str
    title: str
    doc_type: str
    url: str = ""
    status: str = "seed"  # seed|parsed|stub
    confirmed: bool = False


class NormProfile(BaseModel):
    """Собранный набор норм под конкретный объект."""

    signature: str
    object_type: str
    params: dict[str, NormParam] = Field(default_factory=dict)
    sources: list[NormSource] = Field(default_factory=list)
    from_cache: bool = False

    def value(self, category: str, fallback: float) -> float:
        p = self.params.get(category)
        return p.value if p else fallback


# ─────────────────────────── Объёмы и смета ───────────────────────────
class VolumeItem(BaseModel):
    key: str
    title: str
    unit: str
    quantity: float
    formula: str = ""
    norm: str = ""  # документ/коэффициент
    needs_review: bool = False


class EstimateLine(BaseModel):
    no: str
    section: str
    title: str
    norm: str = ""
    unit: str
    quantity: float
    material_price: float = 0.0
    labor_price: float = 0.0
    machine_price: float = 0.0
    total: float = 0.0
    comment: str = ""
    needs_review: bool = False


class EstimateTotals(BaseModel):
    direct: float = 0.0
    overhead: float = 0.0
    overhead_pct: float = 0.0
    contingency: float = 0.0
    contingency_pct: float = 0.0
    subtotal_with_overhead: float = 0.0
    subtotal_with_contingency: float = 0.0
    vat: float = 0.0
    vat_pct: float = 0.0
    grand_total: float = 0.0


class EstimateResult(BaseModel):
    project_name: str
    city: str
    object_type: str
    precision_class: str = "Класс 5 (ориентировочный)"
    warnings: list[str] = Field(default_factory=list)
    sources: list[NormSource] = Field(default_factory=list)
    volumes: list[VolumeItem] = Field(default_factory=list)
    lines: list[EstimateLine] = Field(default_factory=list)
    section_totals: dict[str, float] = Field(default_factory=dict)
    totals: EstimateTotals = Field(default_factory=EstimateTotals)
    contractor_questions: list[str] = Field(default_factory=list)
    clarifications: list[str] = Field(default_factory=list)
    generated_at: str = ""
    llm_narrative: str = ""  # опциональный текст от LLM


# ─────────────────────────── Задачи / статусы ───────────────────────────
class JobStep(BaseModel):
    key: str
    label: str
    status: str = "pending"  # pending|running|done|error
    detail: str = ""


class JobStatus(BaseModel):
    id: str
    status: str
    progress: int
    steps: list[JobStep] = Field(default_factory=list)
    error: str = ""
    estimate_id: Optional[int] = None
    result: Optional[EstimateResult] = None


def to_jsonable(obj: Any) -> Any:
    """Рекурсивная сериализация Pydantic-моделей в JSON-совместимый вид."""
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    return obj
