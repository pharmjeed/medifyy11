"""ملخص المريض بالعربي (م14) — توليد/معاينة/تعديل/تضمين + تصدير PDF مستقل.

الحارس الحاكم: لا توليد قبل البوابة ① (MDF-4231) — يُفرض في طبقة الخدمة.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel

from ...analytics import track
from ...audit import audit
from ...deps import DoctorAuth, DB
from ...envelope import ok
from ...errors import MedifyError
from ...services.features import require_feature
from ...services.patient_summary import (
    generate_patient_summary,
    get_patient_summary,
    update_patient_summary,
)
from ...services.patient_summary_pdf import patient_summary_pdf
from ...services.visits import get_visit_for_doctor

router = APIRouter()

# ملخص المريض ميزة باقة (قرار مالك 2026-08-03) — الحارس على النقاط الأربع كلها
FEATURE = "visit.patient_summary"


@router.post("/visits/{visit_id}/patient-summary")
def create_patient_summary(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """توليد الملخص — بعد البوابة ① حصراً (MDF-4231 قبلها)."""
    require_feature(db, ctx.facility_id, FEATURE)
    visit = get_visit_for_doctor(db, visit_id)
    summary = generate_patient_summary(db, visit)
    audit(db, ctx.facility_id, "patient_summary.generated", "visit", visit.id, ctx.user_id,
          {"version": visit.cycle})
    track("note.exported", ctx.facility_id, "doctor", visit.id,
          format="patient_summary", chars=sum(len(value) for value in summary.values()))
    return ok(get_patient_summary(db, visit))


@router.get("/visits/{visit_id}/patient-summary")
def read_patient_summary(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    require_feature(db, ctx.facility_id, FEATURE)
    visit = get_visit_for_doctor(db, visit_id)
    result = get_patient_summary(db, visit)
    if result is None:
        raise MedifyError("MDF-4041", details={"reason": "patient_summary_not_generated"})
    return ok(result)


class PatientSummaryPatchIn(BaseModel):
    summary: dict[str, Any] | None = None
    included: bool | None = None


@router.patch("/visits/{visit_id}/patient-summary")
def patch_patient_summary(visit_id: uuid.UUID, body: PatientSummaryPatchIn, ctx: DoctorAuth, db: DB):
    """تعديل الطبيب و/أو قرار التضمين (toggle) قبل النقل."""
    require_feature(db, ctx.facility_id, FEATURE)
    visit = get_visit_for_doctor(db, visit_id)
    result = update_patient_summary(db, visit, summary=body.summary, included=body.included)
    audit(db, ctx.facility_id, "patient_summary.updated", "visit", visit.id, ctx.user_id,
          {"version": visit.cycle, "included": result["included"],
           "text_edited": body.summary is not None})
    return ok(result)


@router.get("/visits/{visit_id}/patient-summary/pdf")
def export_patient_summary_pdf(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """PDF عربي RTL بخط IBM Plex Sans Arabic — endpoint تصدير مستقل."""
    require_feature(db, ctx.facility_id, FEATURE)
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state == "voided":
        raise MedifyError("MDF-4235", details={"visit_id": str(visit.id)})
    stored = get_patient_summary(db, visit)
    if stored is None:
        raise MedifyError("MDF-4041", details={"reason": "patient_summary_not_generated"})
    payload = patient_summary_pdf(db, visit, stored)
    audit(db, ctx.facility_id, "patient_summary.exported", "visit", visit.id, ctx.user_id,
          {"version": visit.cycle})
    track("note.exported", ctx.facility_id, "doctor", visit.id,
          format="patient_summary_pdf", bytes=len(payload))
    filename = f"medify-patient-summary-{str(visit.id)[:8]}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
