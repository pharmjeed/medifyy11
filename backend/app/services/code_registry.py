"""خدمة السجل المرجعي للأكواد — قرار مالك 2026-08-02.

المبدأ: سجلنا هو مصدر الحقيقة للكود لا ذاكرة النموذج. أحكام الفحص:
- valid: موجود ونشط — تُؤخذ الصيغة القانونية وإصدار السجل وتاريخ السريان من عندنا.
- inactive: موجود لكنه ملغى — يُعرض بديله (replaced_by) ولا يمر من البوابة ②.
- unknown: النظام محمّل والكود غير موجود — «لا تخمين»: الكود يسقط.
- unchecked: لا صفوف لهذا النظام في السجل — لا تحقق (سلوك ما قبل القرار).
"""
from __future__ import annotations

import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import RegistryCode

RegistryVerdict = str  # "valid" | "inactive" | "unknown" | "unchecked"


def normalize_code(code: str) -> str:
    """مفتاح المطابقة: كبيرة بلا فواصل/شرطات/نقاط — يطابق «E11.9» و«E119» و«40803-00-00» و«408030000»."""
    return re.sub(r"[\s\-\.]", "", str(code)).upper()


def registry_systems(db: Session) -> set[str]:
    """الأنظمة المحمّلة فعلاً في السجل — نظام بلا صفوف لا يُتحقق منه."""
    rows = db.execute(select(RegistryCode.code_system).distinct()).scalars().all()
    return set(rows)


def lookup(db: Session, system: str, code: str) -> RegistryCode | None:
    if not code or not system:
        return None
    return db.execute(
        select(RegistryCode).where(
            RegistryCode.code_system == system,
            RegistryCode.code_norm == normalize_code(code),
        )
    ).scalar_one_or_none()


def check_code(
    db: Session, system: str | None, code: str | None, systems_loaded: set[str]
) -> tuple[RegistryVerdict, RegistryCode | None]:
    if not code or not system or system not in systems_loaded:
        return "unchecked", None
    entry = lookup(db, system, code)
    if entry is None:
        return "unknown", None
    return ("valid" if entry.is_active else "inactive"), entry


def search(db: Session, system: str, query: str, limit: int = 12) -> list[RegistryCode]:
    """بحث الإكمال التلقائي: بادئة الكود أولاً ثم نص الوصف — النشط قبل الملغى."""
    text = query.strip()
    if not text:
        return []
    code_prefix = f"{normalize_code(text)}%"
    desc_pattern = f"%{text}%"
    prefix_match = RegistryCode.code_norm.like(code_prefix)
    stmt = (
        select(RegistryCode)
        .where(
            RegistryCode.code_system == system,
            or_(
                prefix_match,
                RegistryCode.short_desc.ilike(desc_pattern),
                RegistryCode.long_desc.ilike(desc_pattern),
            ),
        )
        .order_by(
            RegistryCode.is_active.desc(),
            prefix_match.desc(),
            RegistryCode.code,
        )
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def system_total(db: Session, system: str) -> int:
    return db.execute(
        select(func.count(RegistryCode.id)).where(RegistryCode.code_system == system)
    ).scalar_one()
