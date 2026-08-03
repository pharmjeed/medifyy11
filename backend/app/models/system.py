"""الجداول العرضية — DOC-04 §٦."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, pk


class AuditLog(Base, TimestampMixin):
    """إلحاقي فقط — يغطي عمليات الأدمن وكل اعتماد/رفع (FR-303/NFR-10). لا محتوى سريرياً في meta_json."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # null = النظام
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MetricEvent(Base, TimestampMixin):
    """حدث قياس (م15) — أرقام فقط في numeric_payload، لا حقل نصي حر إطلاقاً.

    الأبعاد (specialty/clinic) تصنيفات لا محتوى سريري، وvisit_id/physician_id
    معرّفات داخلية. الاستعلامات الإدارية تقرأ من daily_metrics المجمّع لا من هنا.
    """

    __tablename__ = "metric_events"

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    visit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("visits.id"), nullable=True, index=True)
    physician_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    specialty: Mapped[str | None] = mapped_column(Text, nullable=True)
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinics.id"), nullable=True)
    numeric_payload: Mapped[Any] = mapped_column(JSONB, nullable=False)  # أرقام حصراً (يُفرض تطبيقياً)


class DailyMetric(Base, TimestampMixin):
    """تجميع ليلي لكل (يوم، بُعد، مقياس) — مصدر لوحات الإدارة (م15)."""

    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint("facility_id", "day", "dimension", "dimension_key", "metric",
                         name="uq_daily_metrics_slice"),
    )

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    day: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(Text, nullable=False)      # physician | specialty | clinic | facility
    dimension_key: Mapped[str] = mapped_column(Text, nullable=False)  # المعرّف أو الاسم التصنيفي
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class Notification(Base, TimestampMixin):
    """أنواعها حصراً أحداث DOC-12 الـ12 — لا محتوى سريرياً في payload_json."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
