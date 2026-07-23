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
from ...services.visits import get_visit_for_doctor

router = APIRouter()


def _require_gate_two(db, visit: Visit) -> None:
    approval = db.execute(select(Approval).where(Approval.visit_id == visit.id)).scalar_one_or_none()
    if approval is None:
        raise MedifyError("MDF-4232", details={"visit_id": str(visit.id)})


@router.get("/visits/{visit_id}/export/text")
def export_text(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """نص نظيف يُلصق في الـ EMR (F-086) — يُنسخ من الواجهة بنقرة."""
    visit = get_visit_for_doctor(db, visit_id)
    _require_gate_two(db, visit)
    content = note_text(db, visit)
    audit(db, ctx.facility_id, "note.exported", "visit", visit.id, ctx.user_id, {"format": "text"})
    track("note.exported", ctx.facility_id, "doctor", visit.id, format="text", chars=len(content))
    return ok({"format": "text", "content": content, **export_meta(db, visit)})


@router.get("/visits/{visit_id}/export/pdf")
def export_pdf(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """PDF بترويسة وتذييل ثنائيي اللغة (F-038/F-084)."""
    visit = get_visit_for_doctor(db, visit_id)
    _require_gate_two(db, visit)
    payload = note_pdf(db, visit)
    audit(db, ctx.facility_id, "note.exported", "visit", visit.id, ctx.user_id, {"format": "pdf"})
    track("note.exported", ctx.facility_id, "doctor", visit.id, format="pdf", bytes=len(payload))
    filename = export_filename(visit, "pdf")
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
