"""بحث السجل المرجعي للأكواد — قرار مالك 2026-08-02 (تعديل معتمد على DOC-05).

يخدم الإكمال التلقائي في شاشة المراجعة (تعديل رمز الإرشاد) — بيانات مرجعية عامة
بلا محتوى سريري ولا معرّف مريض. دور التطبيق يقرأ الجدول SELECT فقط.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ...deps import DoctorAuth, DB
from ...envelope import ok
from ...services.code_registry import search, system_total

router = APIRouter()


@router.get("/codes/search")
def search_codes(
    ctx: DoctorAuth,
    db: DB,
    system: str = Query(min_length=2, max_length=16),
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=12, ge=1, le=50),
):
    """بادئة الكود أو نص الوصف — النشط أولاً، والملغى يظهر ببديله (لا يُختار)."""
    results = search(db, system, q, limit)
    return ok(
        [
            {
                "code": row.code,
                "short_desc": row.short_desc,
                "long_desc": row.long_desc,
                "chapter": row.chapter,
                "block": row.block,
                "is_active": row.is_active,
                "replaced_by": row.replaced_by,
                "registry_version": row.registry_version,
                "effective_date": row.effective_date.isoformat() if row.effective_date else None,
                "inactive_date": row.inactive_date.isoformat() if row.inactive_date else None,
            }
            for row in results
        ],
        meta={"system": system, "system_total": system_total(db, system)},
    )
