"""الملاحق على المذكرات المعتمدة نهائياً — مسار الإلحاق (قرار مالك 2026-08-03 — CBAHI).

ملحق على مذكرة موقّعة: نص جديد مرتبط بالزيارة الأصلية، له طابعه الزمني وتوقيعه الخاص،
يمر بوابة ① مصغّرة وقد يحتاج بوابة ② إن احتوى على تغييرات ترميز.

المسارات:
- POST /api/v1/visits/{visit_id}/addendums — إضافة ملحق
- GET /api/v1/visits/{visit_id}/addendums — قائمة الملاحق
- PATCH /api/v1/addendums/{addendum_id} — موافقة الدكتور على الملحق (بوابة ① مصغّرة)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...analytics import track
from ...audit import audit
from ...deps import DoctorAuth, DB
from ...envelope import ok
from ...errors import MedifyError
from ...models import (
    Addendum,
    Facility,
    NoteApproval,
    Summary,
    SummarySection,
    User,
    Visit,
)
from ...services.visits import get_visit_for_doctor
from ...notify import notify

router = APIRouter()


class AddendumCreate(BaseModel):
    """إنشاء ملحق جديد على مذكرة معتمدة.

    - content: محتوى الملحق — نص حر أو أقسام مثل الملخص الأصلي
    - reason: سبب الإضافة (اختياري — يُدوّن في audit_logs)
    """

    content: dict[str, Any] = Field(..., description="محتوى الملحق: {sections: [{section_key, content}]}")
    reason: str | None = Field(None, description="سبب الإضافة")


class AddendumResponse(BaseModel):
    """استجابة الملحق المُنشأ."""

    id: uuid.UUID
    visit_id: uuid.UUID
    created_at: dt.datetime
    created_by: uuid.UUID
    content_json: dict[str, Any]
    is_approved: bool
    note_approval_id: uuid.UUID | None


@router.post("/visits/{visit_id}/addendums")
async def create_addendum(
    visit_id: uuid.UUID,
    payload: AddendumCreate,
    auth: DoctorAuth = DoctorAuth(),
    db: Session = DB(),
) -> dict[str, Any]:
    """إضافة ملحق على مذكرة معتمدة نهائياً.

    الشروط:
    - الزيارة يجب أن تكون في حالة approved أو uploaded (اعتُمدت بالفعل)
    - الدكتور يجب أن يكون صاحب الزيارة الأصلية
    - الملحق ينتظر موافقة الدكتور (بوابة ① مصغّرة) قبل أن يُرسل

    المخرج:
    - Addendum جديد بحالة pending
    - إشعار للدكتور بضرورة موافقته
    """
    visit = get_visit_for_doctor(db, visit_id, auth.user_id)
    if visit.state not in ("approved", "uploaded"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "MDF-4227",
                    "message_ar": "لا يمكن إضافة ملحق على مذكرة لم تُعتمد بعد.",
                    "message_en": "Addendum cannot be created for unapproved visits.",
                }
            },
        )

    # تحقق من وجود اعتماد أصلي (note_approval)
    original_approval = db.execute(
        select(NoteApproval).where(NoteApproval.visit_id == visit_id)
    ).scalar_one_or_none()
    if original_approval is None:
        raise HTTPException(
            status_code=400,
            detail="Original note approval not found (visit not properly approved)",
        )

    # إنشاء ملحق جديد
    addendum = Addendum(
        id=uuid.uuid7(),
        visit_id=visit_id,
        facility_id=auth.facility_id,
        created_by=auth.user_id,
        created_at=dt.datetime.now(dt.timezone.utc),
        content_json=payload.content or {},
        is_approved=False,
        note_approval_id=None,
    )
    db.add(addendum)
    db.flush()

    # تسجيل في سجل التدقيق
    audit(
        db, auth.facility_id, "addendum.created",
        addendum.id, {"visit_id": str(visit_id), "reason": payload.reason or ""}
    )

    # إشعار الدكتور
    notify(
        db, auth.facility_id, auth.user_id, "dr.addendum_pending",
        {"visit_id": str(visit_id), "addendum_id": str(addendum.id)}
    )

    track(
        "addendum.created", auth.facility_id, "doctor", visit_id,
        addendum_id=str(addendum.id)
    )

    return ok({"addendum": AddendumResponse.model_validate(addendum).model_dump()})


@router.get("/visits/{visit_id}/addendums")
async def list_addendums(
    visit_id: uuid.UUID,
    auth: DoctorAuth = DoctorAuth(),
    db: Session = DB(),
) -> dict[str, Any]:
    """قائمة الملاحق على زيارة معتمدة.

    تُرجع جميع الملاحق بالترتيب الزمني (الأحدث أولاً).
    """
    visit = get_visit_for_doctor(db, visit_id, auth.user_id)

    addendums = db.execute(
        select(Addendum)
        .where(Addendum.visit_id == visit_id)
        .order_by(Addendum.created_at.desc())
    ).scalars().all()

    return ok({
        "addendums": [
            AddendumResponse.model_validate(a).model_dump()
            for a in addendums
        ]
    })


class AddendumApprove(BaseModel):
    """موافقة الدكتور على ملحق (بوابة ① مصغّرة)."""

    pass


@router.patch("/addendums/{addendum_id}/approve")
async def approve_addendum(
    addendum_id: uuid.UUID,
    auth: DoctorAuth = DoctorAuth(),
    db: Session = DB(),
) -> dict[str, Any]:
    """موافقة الدكتور على ملحق (بوابة ① مصغّرة).

    الشروط:
    - الدكتور يجب أن يكون صاحب الزيارة الأصلية
    - الملحق يجب أن يكون pending (لم يُوافق عليه بعد)

    المخرج:
    - Addendum محدّث بـ is_approved=True و note_approval_id
    - يصبح الملحق جاهزاً للرفع/التصدير
    """
    addendum = db.execute(
        select(Addendum).where(Addendum.id == addendum_id)
    ).scalar_one_or_none()

    if addendum is None:
        raise HTTPException(status_code=404, detail="Addendum not found")

    visit = get_visit_for_doctor(db, addendum.visit_id, auth.user_id)

    if addendum.is_approved:
        raise HTTPException(
            status_code=422,
            detail="Addendum is already approved"
        )

    # إنشاء bossapproval note مصغّرة (بوابة ① مصغّرة)
    summary_hash = hashlib.sha256(
        str(addendum.content_json).encode()
    ).hexdigest()

    note_approval = NoteApproval(
        id=uuid.uuid7(),
        visit_id=addendum.visit_id,
        facility_id=auth.facility_id,
        approved_by=auth.user_id,
        approved_at=dt.datetime.now(dt.timezone.utc),
        summary_hash=summary_hash,
    )
    db.add(note_approval)
    db.flush()

    # تحديث الملحق
    addendum.is_approved = True
    addendum.note_approval_id = note_approval.id
    db.flush()

    # تسجيل في سجل التدقيق
    audit(
        db, auth.facility_id, "addendum.approved",
        addendum.id, {"visit_id": str(addendum.visit_id)}
    )

    track(
        "addendum.approved", auth.facility_id, "doctor", addendum.visit_id,
        addendum_id=str(addendum_id)
    )

    return ok({"addendum": AddendumResponse.model_validate(addendum).model_dump()})
