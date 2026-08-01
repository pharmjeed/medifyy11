"""السجل المرجعي للأكواد — قرار مالك 2026-08-02 (تعديل معتمد على DOC-04).

- registry_codes: مرجع منصّي عام (ليس مستأجرياً — لا RLS، نمط plans): أكواد الأنظمة
  (SBS · ICD10AM · ACHI · SFDA · GMDN) بحالتها (نشط/ملغى) وتاريخ سريانها وبديل الملغى.
- المصدر الرسمي: SBS من ملف CHI «Technical List» (SBS_V2_Code_list.xlsx) عبر
  scripts/import_codes.py · ICD-10-AM مرخّص (IHACPA) عبر قنوات CHI/nphies.
  **لا يُستورد ICD-10-CM الأمريكي — nphies يعتمد ICD-10-AM حصراً.**
- دور التطبيق SELECT فقط؛ الكتابة بدور المالك (الاستيراد) حصراً.
- سجل فارغ لنظامٍ ما = لا تحقق لذلك النظام (السلوك السابق للقرار) — التفعيل بالاستيراد.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, Date, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, pk


class RegistryCode(Base, TimestampMixin):
    """كود مرجعي واحد — code هو الصيغة القانونية للعرض (مثل 73000-00-60 أو I10)،
    وcode_norm مفتاح المطابقة (كبيرة بلا فواصل/شرطات/نقاط) فيطابق «E119» و«E11.9» معاً."""

    __tablename__ = "registry_codes"
    __table_args__ = (
        UniqueConstraint("code_system", "code_norm", name="uq_registry_system_code_norm"),
        Index("ix_registry_system_norm", "code_system", "code_norm"),
    )

    id: Mapped[uuid.UUID] = pk()
    code_system: Mapped[str] = mapped_column(Text, nullable=False)  # ICD10AM | ACHI | SBS | SFDA | GMDN
    code: Mapped[str] = mapped_column(Text, nullable=False)
    code_norm: Mapped[str] = mapped_column(Text, nullable=False)
    short_desc: Mapped[str] = mapped_column(Text, nullable=False)
    long_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter: Mapped[str | None] = mapped_column(Text, nullable=True)
    block: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    inactive_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(Text, nullable=True)  # بديل الكود الملغى (Inactive Code Mapping)
    registry_version: Mapped[str] = mapped_column(Text, nullable=False)  # مثل «SBS V2.0»
