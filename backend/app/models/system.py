"""الجداول العرضية — DOC-04 §٦."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, func
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


class Notification(Base, TimestampMixin):
    """أنواعها حصراً أحداث DOC-12 الـ12 — لا محتوى سريرياً في payload_json."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
