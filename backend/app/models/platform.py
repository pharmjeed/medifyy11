"""جداول طبقة المنصة — السوبر أدمن والباقات والحوكمة (DOC-20 v1.1 معتمدة 2026-07-16).

- platform_admins: حسابات مالك ميديفاي — خارج الاستئجار كلياً، لا يصلها دور medify_app.
  خمس درجات (owner/ops/finance/support/read_only) + 2FA (سرّ مشفّر عموداً + رموز استرداد هاش).
- plans: كتالوج تكلفة الدكتور لكل دورة فوترة (تعديل مالك: لا باقات ميزات — سعر للدكتور فقط).
- platform_audit_logs: سجل المنصة الموحّد — إلحاقي فقط (تدوين مزدوج مع audit_logs المنشأة).
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..crypto import EncryptedText
from .base import Base, TimestampMixin, pk

BILLING_CYCLE = Enum("monthly", "yearly", name="billing_cycle")
PLATFORM_ROLE = Enum("owner", "ops", "finance", "support", "read_only", name="platform_role")


class PlatformAdmin(Base, TimestampMixin):
    """سوبر أدمن المنصة — يدير المنشآت والتسعير والمدفوعات، ولا يقرأ محتوى سريرياً أبداً."""

    __tablename__ = "platform_admins"

    id: Mapped[uuid.UUID] = pk()
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)  # argon2id
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # الحوكمة (DOC-20 §١.٢) — الدرجة تُحقن من القاعدة لا من الرمز
    role: Mapped[str] = mapped_column(PLATFORM_ROLE, nullable=False, default="owner")
    # المصادقة الثنائية (DOC-20 §١.٣)
    totp_secret_encrypted: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recovery_codes: Mapped[Any | None] = mapped_column(JSONB, nullable=True)  # هاشات SHA-256 فقط
    # دورة حياة الحساب
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_admins.id"), nullable=True)
    disabled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Plan(Base, TimestampMixin):
    """باقة = تكلفة الدكتور لدورة فوترة + ما تُظهره للدكتور (قرار مالك 2026-08-03).

    subscriptions.plan يشير تطبيقياً إلى code — يُتحقق عند الإسناد.
    """

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("code", name="uq_plans_code"),)

    id: Mapped[uuid.UUID] = pk()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    seat_price_sar: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)  # تكلفة الدكتور
    billing_cycle: Mapped[str] = mapped_column(BILLING_CYCLE, nullable=False, default="monthly")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # مميزات الباقة (هجرة 0021) — {feature_key: bool} لمفاتيح app.features حصراً.
    # NULL أو مفتاح غائب = افتراض الكتالوج، فالباقات القائمة لا تفقد شيئاً بالترقية.
    features: Mapped[Any | None] = mapped_column(JSONB, nullable=True)


class PlatformSetting(Base, TimestampMixin):
    """إعدادات المنصة (مفتاح/قيمة) — توجيه مالك 2026-08-01: اختيار نموذج الذكاء من الكونسول.

    محجوبة كلياً عن medify_app — تُقرأ عبر جلسة النظام عند بناء المحركات فقط.
    """

    __tablename__ = "platform_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_platform_settings_key"),)

    id: Mapped[uuid.UUID] = pk()
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_admins.id"), nullable=True)


class PlatformAuditLog(Base, TimestampMixin):
    """سجل تدقيق المنصة الموحّد (W-SA-09) — إلحاقي فقط، محجوب عن medify_app."""

    __tablename__ = "platform_audit_logs"

    id: Mapped[uuid.UUID] = pk()
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_admins.id"), nullable=True)
    actor_username: Mapped[str] = mapped_column(Text, nullable=False)
    actor_role: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    facility_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class PlatformDefaultPrompt(Base, TimestampMixin):
    """برومبتات ديفولت من SuperAdmin — محجوبة كلياً عن medify_app (SELECT فقط)."""

    __tablename__ = "platform_default_prompts"
    __table_args__ = (UniqueConstraint("template_type", "version", name="uq_platform_prompts_type_version"),)

    id: Mapped[uuid.UUID] = pk()
    template_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)  # first_visit, follow_up, consultation
    prompt_content: Mapped[str] = mapped_column(Text, nullable=False)  # محتوى البرومبت الكامل
    version: Mapped[str] = mapped_column(Text, nullable=False, default="1.0")  # 1.0, 1.1, 1.2 إلخ
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform_admins.id"), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_admins.id"), nullable=True)
