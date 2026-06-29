"""Pydantic-схемы: вход, нормативный профиль, объёмы, смета, статусы."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class MassingBox(BaseModel):
    """Прямоугольный объём массинга. План: угол (x,y), габариты (w,d) в метрах;
    floors — этажей в блоке; base — этажей-смещение снизу (башня на стилобате)."""

    x: float = 0.0
    y: float = 0.0
    w: float = 1.0  # ширина (вдоль X), м
    d: float = 1.0  # глубина (вдоль Y), м
    floors: int = 1
    base: int = 0


class BuildingForm(BaseModel):
    """Результат ИИ-генерации формы здания с нормоконтролем.
    status: ok — реализуема как запрошено; adjusted — изменена под нормы/физику РК;
    rejected — принципиально нереализуема (boxes пуст)."""

    status: str = "ok"          # ok | adjusted | rejected
    message: str = ""           # объяснение пользователю (нарушение/правка/отказ)
    floor_height: float = 3.0
    boxes: list[MassingBox] = Field(default_factory=list)


# ─────────────────────────── Вход от заказчика ───────────────────────────
class BuildingInput(BaseModel):
    project_name: str = "Черновая смета объекта"
    city: str = "Астана / Казахстан"
    object_type: str = "Жилой дом"
    floors: int = 10
    total_area: float = 1500.0  # м² = длина × ширина × этажность (10×15×10)
    building_length: float = 10.0  # м
    building_width: float = 15.0  # м
    floor_height: float = 3.0  # м
    form: str = "box"  # форма здания: box|tower|court|stepped|dome (влияет на застройку/фасад)
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
    # Произвольная форма (набор блоков). Если задана — геометрия берётся из неё,
    # а не из длина×ширина×фактор формы. None → прежнее поведение.
    massing: Optional[list[MassingBox]] = None

    @field_validator("floors", mode="before")
    @classmethod
    def _floors_whole(cls, v):
        """Этажи не могут быть дробными: округляем к целому, минимум 1.
        Нечисловое отдаём дальше — стандартная валидация его отвергнет."""
        try:
            return max(1, round(float(v)))
        except (TypeError, ValueError):
            return v

    @field_validator("floor_height", mode="before")
    @classmethod
    def _floor_height_positive(cls, v):
        """Высота этажа должна быть положительной (иначе отрицательные объём/фасад)."""
        try:
            f = float(v)
            return f if f > 0 else 3.0
        except (TypeError, ValueError):
            return v

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
    link_ok: Optional[bool] = None  # доступность ссылки: True/False/None


class CrossCheck(BaseModel):
    """Итог кросс-проверки норм вторым ИИ (ансамбль)."""

    enabled: bool = False
    ran: bool = False
    verifier: str = ""
    agreed: int = 0
    disputed: int = 0
    missing: int = 0
    extra: int = 0
    extra_keys: list[str] = Field(default_factory=list)
    reason: str = ""


class NormProfile(BaseModel):
    """Собранный набор норм под конкретный объект."""

    signature: str
    object_type: str
    params: dict[str, NormParam] = Field(default_factory=dict)
    sources: list[NormSource] = Field(default_factory=list)
    from_cache: bool = False
    cross_check: Optional["CrossCheck"] = None

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


class ResourceLine(BaseModel):
    code: str
    name: str
    kind: str  # "material" | "labor" | "machine"
    unit: str
    consumption: float
    price: float = 0.0
    source: str = ""       # происхождение цены: seed|ndcs|erer|ssc|manual|llm|benchmark
    updated_at: str = ""   # дата актуализации цены (ISO), для проверки свежести


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
    resources: list[ResourceLine] = []
    price_source: str = ""   # сводный источник цен строки
    price_date: str = ""     # самая поздняя дата актуализации цен строки (ISO)
    price_stale: bool = False  # цены не обновлялись ≥ порога (по умолчанию 6 мес)


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


class EstimateCard(BaseModel):
    id: int
    name: str
    object_type: str
    city: str
    status: str
    total: float
    version_count: int
    message_count: int
    updated_at: str


class EstimateCreate(BaseModel):
    name: str = ""
    input: Optional[BuildingInput] = None


class EstimatePatch(BaseModel):
    name: Optional[str] = None
    input: Optional[BuildingInput] = None


class ManualEditRequest(BaseModel):
    lines: list[EstimateLine]
    input: Optional[BuildingInput] = None


class RollbackRequest(BaseModel):
    version_number: int


class RecommendationAdd(BaseModel):
    key: str = Field(min_length=1)


class ObjectCreate(BaseModel):
    name: str = ""
    city: str = "Алматы"
    lat: float
    lon: float
    polygon: Optional[dict] = None
    area_m2: float = 0.0
    notes: str = ""


class ObjectPatch(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    notes: Optional[str] = None


class ObjectCard(BaseModel):
    id: int
    name: str
    city: str
    lat: float
    lon: float
    area_m2: float
    status: str
    source: str
    score: Optional[float]
    estimate_count: int
    updated_at: str


class ZoneVerdict(BaseModel):
    status: str                       # allowed | restricted | unknown
    land_use: str = ""                # целевое назначение (tsn_ru)
    kad_nomer: str = ""
    zone: str = ""                    # "водоохранная зона" | "кадастровый участок" | ""
    source: str = "map.gov.kz/geoserver (WFS)"
    note: str = ""
    checked_at: Optional[str] = None


class SuggestPricesRequest(BaseModel):
    source: str = "satu"


class ChatPost(BaseModel):
    message: str = Field(min_length=1)


class BenchmarkPriceIn(BaseModel):
    """Строка внутреннего справочника цен (бенчмаркинг)."""
    work_key: str
    code: str
    name: str = ""
    kind: str  # material | labor | machine
    unit: str
    consumption: float = 1.0
    price: float = 0.0
    region: str = "KZ"


class SettingsUpdate(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    use_search: Optional[bool] = None
    cross_check_enabled: Optional[bool] = None
    cross_check_provider: Optional[str] = None
    price_inflation_annual_pct: Optional[float] = None


class TestConnectionRequest(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class PromptUpdate(BaseModel):
    body: str = Field(min_length=1)


def to_jsonable(obj: Any) -> Any:
    """Рекурсивная сериализация Pydantic-моделей в JSON-совместимый вид."""
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    return obj
