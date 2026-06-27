"""Справочник индикативных цен РК (Астана, 2026) и их резолв.

Цены ориентировочные, требуют уточнения у поставщиков. Источник базовых значений —
рыночная практика и пример сметы. Хранятся в БД (таблица price_items),
переопределяемы по региону.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PriceItem


@dataclass(frozen=True)
class Price:
    title: str
    unit: str
    material: float
    labor: float
    machine: float = 0.0


# key → Price (KZT за единицу): материал / работа / машины
PRICES: dict[str, Price] = {
    "excavation": Price("Разработка грунта", "м³", 0, 1500, 500),
    "soil_removal": Price("Вывоз грунта", "м³", 0, 500, 1000),
    "backfill": Price("Обратная засыпка", "м³", 0, 800, 200),
    "concrete": Price("Бетон В25 (с доставкой)", "м³", 30000, 10000, 5000),
    "rebar": Price("Арматура AIII (с монтажом)", "т", 350000, 100000, 0),
    "formwork": Price("Опалубка", "м²", 2000, 3000, 0),
    "partitions": Price("Кладка перегородок (газоблок)", "м²", 3000, 2500, 0),
    "waterproofing_foundation": Price("Гидроизоляция фундамента", "м²", 1500, 800, 0),
    "insulation_foundation": Price("Теплоизоляция фундамента (ЭППС)", "м²", 3000, 700, 0),
    "insulation_walls": Price("Теплоизоляция стен (минвата)", "м²", 2500, 800, 0),
    "insulation_roof": Price("Теплоизоляция кровли (минвата)", "м²", 2000, 700, 0),
    "roof": Price("Мягкая кровля (2 слоя)", "м²", 3000, 1500, 0),
    "facade": Price("Вентилируемый фасад (базовый)", "м²", 8000, 4000, 0),
    "glazing": Price("Окна ПВХ / витражи", "м²", 25000, 5000, 0),
    "screed": Price("Стяжка полов", "м²", 1500, 1000, 0),
    "wall_finish": Price("Штукатурка, шпатлёвка, покраска стен", "м²", 1800, 2200, 0),
    "ceiling_finish": Price("Шпатлёвка и покраска потолков", "м²", 800, 1000, 0),
    "hvac": Price("Монтаж системы ОВиК (базовая)", "м²", 3000, 1500, 0),
    "plumbing": Price("Монтаж систем ВК (базовая)", "м²", 2000, 1000, 0),
    "electrical": Price("Монтаж электросетей (базовая)", "м²", 3500, 2000, 0),
    "low_current": Price("Монтаж слаботочных систем", "м²", 1000, 500, 0),
    "landscaping": Price("Благоустройство и наружные сети", "м²", 2000, 1000, 0),
}

# Объёмные позиции, которые тарифицируются по общему прайс-ключу.
PRICE_KEY_ALIAS: dict[str, str] = {
    "foundation_concrete": "concrete",
    "frame_concrete": "concrete",
}


def price_key_for(volume_key: str) -> str:
    return PRICE_KEY_ALIAS.get(volume_key, volume_key)


def seed_prices(db: Session, region: str = "KZ") -> None:
    """Идемпотентно засеять справочник цен."""
    for key, price in PRICES.items():
        exists = db.scalar(
            select(PriceItem).where(
                PriceItem.key == key, PriceItem.region == region
            )
        )
        if exists:
            continue
        db.add(
            PriceItem(
                key=key,
                title=price.title,
                unit=price.unit,
                material_price=price.material,
                labor_price=price.labor,
                machine_price=price.machine,
                region=region,
                source="seed: рыночная практика РК (Астана, 2026)",
            )
        )
    db.commit()


def get_price(db: Session, volume_key: str, region: str = "KZ") -> Price:
    """Резолв цены: БД(region) → БД(KZ) → встроенный дефолт → нули."""
    key = price_key_for(volume_key)
    for reg in (region, "KZ"):
        row = db.scalar(
            select(PriceItem).where(PriceItem.key == key, PriceItem.region == reg)
        )
        if row:
            return Price(
                title=row.title,
                unit=row.unit,
                material=row.material_price,
                labor=row.labor_price,
                machine=row.machine_price,
            )
    return PRICES.get(key, Price(key, "ед.", 0, 0, 0))
