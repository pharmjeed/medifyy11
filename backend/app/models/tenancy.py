"""جداول الهوية والاستئجار والاشتراك — DOC-04 §٣."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..crypto import EncryptedText
from .base import Base, TimestampMixin, pk

FACILITY_STATUS = Enum("active", "suspended", "archived", name="facility_status")
USER_ROLE = Enum("admin", "doctor", name="user_role")
SEAT_EVENT_REASON = Enum("expand", "reduce", "activate_dr", "deactivate_dr", name="seat_event_reason")
INVOICE_STATUS = Enum("due", "paid", "overdue", "void", name="invoice_status")
INTEGRATION_MODE = Enum("test", "live", name="integration_mode")
CODING_SYSTEM = Enum("ICD10AM", "ACHI", "SBS", "SFDA", name="coding_system")


class Facility(Base, TimestampMixin):
    __tablename__ = "facilities"

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    commercial_reg: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(FACILITY_STATUS, nullable=False, default="active")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("facility_id", "username", name="uq_users_facility_username"),
        CheckConstraint("role IN ('admin','doctor')", name="ck_users_two_roles_only"),
    )

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(USER_ROLE, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)  # إلزامي للأدمن (يُفحص تطبيقياً)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)  # argon2id
    specialty: Mapped[str | None] = mapped_column(Text, nullable=True)
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinics.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Clinic(Base, TimestampMixin):
    __tablename__ = "clinics"

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("facility_id", name="uq_subscriptions_facility"),)

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False)
    seats_total: Mapped[int] = mapped_column(Integer, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="monthly")
    billing_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class SeatEvent(Base, TimestampMixin):
    """سجل زمني لكل تغيّر في المقاعد — أعمدة DOC-04 حرفياً (D-18: بلا facility_id، RLS عبر الاشتراك)."""

    __tablename__ = "seat_events"

    id: Mapped[uuid.UUID] = pk()
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"), nullable=False, index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(SEAT_EVENT_REASON, nullable=False)
    # NULL = فعل المنصة (السوبر أدمن/النظام) — موازٍ لـ audit_logs.actor_user_id (هجرة 0002)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"), nullable=False)
    number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    period_start: Mapped[dt.date] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[dt.date] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_sar: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    vat_sar: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)  # VAT 15% مفصولة
    status: Mapped[str] = mapped_column(INVOICE_STATUS, nullable=False, default="due")
    issued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class PasswordResetToken(Base, TimestampMixin):
    """استعادة كلمة مرور الأدمن (W-206) — يُخزَّن الهاش فقط، صالح 30 دقيقة ولمرة واحدة."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationConfig(Base, TimestampMixin):
    __tablename__ = "integration_configs"
    __table_args__ = (UniqueConstraint("facility_id", name="uq_integration_facility"),)

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_secret_encrypted: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    mode: Mapped[str] = mapped_column(INTEGRATION_MODE, nullable=False, default="test")
    last_test_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class CodingSystemConfig(Base, TimestampMixin):
    __tablename__ = "coding_system_configs"
    __table_args__ = (
        UniqueConstraint("facility_id", "system", name="uq_coding_facility_system"),
        # ICD-10-AM لا يقبل التعطيل (قرار مالك 2026-07-14 — DOC-04 §٣)
        CheckConstraint("NOT (system = 'ICD10AM' AND is_active = false)", name="ck_icd10am_always_active"),
    )

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    system: Mapped[str] = mapped_column(CODING_SYSTEM, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False, default="2024")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
