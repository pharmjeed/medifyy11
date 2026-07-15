"""جداول طبقة المنصة — السوبر أدمن والباقات (قرار مالك 2026-07-15).

- platform_admins: حسابات مالك ميديفاي — خارج الاستئجار كلياً، لا يصلها دور medify_app.
- plans: كتالوج الباقات (سعر المقعد/الدورة) — قراءة فقط لدور التطبيق (التسعير في الفوترة).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Enum, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, pk

BILLING_CYCLE = Enum("monthly", "yearly", name="billing_cycle")


class PlatformAdmin(Base, TimestampMixin):
    """سوبر أدمن المنصة — يدير كل المنشآت والباقات والمدفوعات، ولا يقرأ محتوى سريرياً أبداً."""

    __tablename__ = "platform_admins"

    id: Mapped[uuid.UUID] = pk()
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)  # argon2id
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Plan(Base, TimestampMixin):
    """باقة اشتراك — subscriptions.plan يشير إلى code (مرجع تطبيقي — يُتحقق عند الإسناد)."""

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("code", name="uq_plans_code"),)

    id: Mapped[uuid.UUID] = pk()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    seat_price_sar: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(BILLING_CYCLE, nullable=False, default="monthly")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
