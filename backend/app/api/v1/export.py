"""تصدير المذكرة المعتمدة — وضع الجسر قبل اكتمال التكامل (A3، توجيه المالك 2026-07-22).

القاعدة غير القابلة للتفاوض تبقى كما هي: **لا خروج بيانات قبل البوابة ②**.
هنا تُفرض تطبيقياً بـ MDF-4232، وفي القاعدة بأن upload_jobs لا تُنشأ بلا approval.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from sqlalchemy import select

from ...analytics import track
from ...audit import audit
from ...deps import DoctorAuth, DB
from ...envelope import ok
from ...errors import MedifyError
from ...models import Approval, Visit
from ...services.export import export_filename, export_meta, note_pdf, note_text
from ...services.features import require_feature
from ...services.versions import latest_uploaded_version
from ...services.visits import get_visit_for_doctor

router = APIRouter()


def _require_exportable(db, visit: Visit) -> None:
    """المُبطلة مختومة (410 — م4) قبل أي فحص بوابة؛ ثم لا خروج بيانات قبل البوابة ②.

    م6: أثناء إعداد نسخة جديدة (reopen) تبقى آخر منقولة قابلة للتصدير — البوابة
    تتحقق من اعتماد الدورة الحالية أو وجود نسخة منقولة سابقة.
    """
    if visit.state == "voided":
        raise MedifyError("MDF-4235", details={"visit_id": str(visit.id)})
    approval = db.execute(
        select(Approval).where(Approval.visit_id == visit.id, Approval.cycle == visit.cycle)
    ).scalar_one_or_none()
    if approval is None and latest_uploaded_version(db, visit.id) is None:
        raise MedifyError("MDF-4232", details={"visit_id": str(visit.id)})


@router.get("/visits/{visit_id}/export/text")
def export_text(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB, version: int | None = None):
    """نص نظيف يُلصق في الـ EMR (F-086) — ?version=N لقطة مجمّدة، الافتراضي آخر منقولة."""
    require_feature(db, ctx.facility_id, "visit.export_text")
    visit = get_visit_for_doctor(db, visit_id)
    _require_exportable(db, visit)
    content = note_text(db, visit, version)
    audit(db, ctx.facility_id, "note.exported", "visit", visit.id, ctx.user_id,
          {"format": "text", "version": version})
    track("note.exported", ctx.facility_id, "doctor", visit.id, format="text", chars=len(content))
    return ok({"format": "text", "content": content, **export_meta(db, visit, version)})


@router.get("/visits/{visit_id}/export/pdf")
def export_pdf(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB, version: int | None = None):
    """PDF بترويسة وتذييل ثنائيي اللغة (F-038/F-084) — ?version=N لقطة مجمّدة (م6)."""
    require_feature(db, ctx.facility_id, "visit.export_pdf")
    visit = get_visit_for_doctor(db, visit_id)
    _require_exportable(db, visit)
    payload = note_pdf(db, visit, version)
    audit(db, ctx.facility_id, "note.exported", "visit", visit.id, ctx.user_id,
          {"format": "pdf", "version": version})
    track("note.exported", ctx.facility_id, "doctor", visit.id, format="pdf", bytes=len(payload))
    meta = export_meta(db, visit, version)
    filename = export_filename(visit, "pdf", meta.get("version"))
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
