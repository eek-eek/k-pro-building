"""ORM-модели: реестр норм, правила, кэш знаний, цены, сметы, задачи."""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class NormDocument(Base):
    """Реестр нормативных документов РК (СН РК, СНиП, СП РК, ГОСТ, ТР)."""

    __tablename__ = "norm_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(String(32))  # СН РК / СНиП / СП РК / ГОСТ / ТР
    url: Mapped[str] = mapped_column(Text, default="")
    # Типы объектов, к которым применим документ (список строк в JSON)
    object_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="seed")  # seed|parsed|stub
    excerpt: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    rules: Mapped[list["NormRule"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class NormRule(Base):
    """Структурированное нормативное правило (коэффициент/требование)."""

    __tablename__ = "norm_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32), default="")
    # Условия применимости: {"structure_type": "...", "foundation_type": "..."}
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(16), default="llm")  # seed|llm|document
    note: Mapped[str] = mapped_column(Text, default="")
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("norm_documents.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)

    document: Mapped[NormDocument | None] = relationship(back_populates="rules")


class KnowledgeCache(Base):
    """Кэш собранного нормативного профиля под сигнатуру входа."""

    __tablename__ = "knowledge_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signature: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    object_type: Mapped[str] = mapped_column(String(64))
    profile: Mapped[dict[str, Any]] = mapped_column(JSON)  # сериализованный NormProfile
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class PriceItem(Base):
    """Справочная цена ресурса/работы по региону."""

    __tablename__ = "price_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32))
    material_price: Mapped[float] = mapped_column(Float, default=0.0)
    labor_price: Mapped[float] = mapped_column(Float, default=0.0)
    machine_price: Mapped[float] = mapped_column(Float, default=0.0)
    region: Mapped[str] = mapped_column(String(64), default="KZ")
    source: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)


class Estimate(Base):
    """Контейнер версионируемого проекта сметы."""

    __tablename__ = "estimates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    object_type: Mapped[str] = mapped_column(String(64), index=True, default="")
    city: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    object_id: Mapped[int | None] = mapped_column(
        ForeignKey("building_objects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimate_versions.id", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    versions: Mapped[list["EstimateVersion"]] = relationship(
        back_populates="estimate",
        cascade="all, delete-orphan",
        order_by="EstimateVersion.version_number",
        foreign_keys="EstimateVersion.estimate_id",
    )
    chat_messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="estimate",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )
    # back_populates намеренно опущен: циклический FK разрешается через post_update=True
    current_version: Mapped["EstimateVersion | None"] = relationship(
        "EstimateVersion", foreign_keys=[current_version_id], post_update=True
    )


class EstimateVersion(Base):
    """Неизменяемый снимок сметы на один момент времени."""

    __tablename__ = "estimate_versions"
    __table_args__ = (UniqueConstraint("estimate_id", "version_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, index=True)
    input: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    # Намеренно обязателен (без default): провенанс всегда указывает вызывающий код
    source: Mapped[str] = mapped_column(String(16), index=True)  # initial|llm_edit|manual_edit|rollback
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    estimate: Mapped["Estimate"] = relationship(
        back_populates="versions", foreign_keys=[estimate_id]
    )


class ChatMessage(Base):
    """Один ход чата внутри сметы."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    # Сырой FK без ORM-связи по замыслу: соединяйте явно в запросах
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimate_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    estimate: Mapped["Estimate"] = relationship(back_populates="chat_messages")


class Prompt(Base):
    """Редактируемый системный промпт, посеянный из значений по умолчанию в коде."""

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class AppSetting(Base):
    """Настройка времени выполнения ключ-значение, переопределяющая .env (пустое значение = не задано)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Job(Base):
    """Асинхронная задача расчёта (для статусов в реальном времени)."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|error
    progress: Mapped[int] = mapped_column(Integer, default=0)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimates.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class BuildingObject(Base):
    """Объект строительства: местоположение, контур участка, концепт."""

    __tablename__ = "building_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    city: Mapped[str] = mapped_column(String(128), default="Алматы")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    polygon: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    area_m2: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|selected
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual|auto
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    zone_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # allowed|restricted|unknown
    zone_land_use: Mapped[str] = mapped_column(Text, default="")
    zone_kad_nomer: Mapped[str] = mapped_column(String(64), default="")
    zone_note: Mapped[str] = mapped_column(Text, default="")
    zone_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Unit(Base):
    """Реестр канонических единиц измерения (см. app/calc/units.py)."""

    __tablename__ = "units"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(64), default="")
    dimension: Mapped[str] = mapped_column(String(16))  # labor_time|machine_time|mass|volume|area|count|length|set
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class WorkResource(Base):
    """Ресурсный состав работы (вынос COMPOSITIONS в БД, с провенансом)."""

    __tablename__ = "work_resources"
    __table_args__ = (
        UniqueConstraint("work_key", "code", "region", "price_level",
                         name="uq_work_resource"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_key: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(64))
    official_code: Mapped[str] = mapped_column(String(64), default="")  # код ЕРЕР/ССЦ (Phase 2)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))  # material|labor|machine
    unit: Mapped[str] = mapped_column(String(16))
    consumption: Mapped[float] = mapped_column(Float)
    rank: Mapped[str] = mapped_column(String(16), default="")  # разряд (для labor)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16), default="seed")  # seed|ndcs|erer|ssc|manual
    price_level: Mapped[str] = mapped_column(String(48), default="")
    region: Mapped[str] = mapped_column(String(64), default="KZ")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class GeneralizedIndicator(Base):
    """Укрупнённый показатель стоимости строительства РК (НДЦС/УСН РК), ₸ за единицу.

    Ориентир/сверка к ресурсной смете. Значения из официальных сборников РК;
    до подтверждения помечаются needs_review (предварительные)."""

    __tablename__ = "generalized_indicators"
    __table_args__ = (
        UniqueConstraint("object_type", "region", "price_level",
                         name="uq_generalized_indicator"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    region: Mapped[str] = mapped_column(String(64), default="KZ")
    value: Mapped[float] = mapped_column(Float)  # ₸ за единицу (обычно м² общей площади)
    unit: Mapped[str] = mapped_column(String(16), default="м²")
    price_level: Mapped[str] = mapped_column(String(48), default="")
    source_code: Mapped[str] = mapped_column(String(64), default="")  # напр. НДЦС РК 8.02-01
    source_url: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
