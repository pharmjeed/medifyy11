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

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ...audit import audit
from ...deps import DoctorAuth, DB
from ...envelope import ok
from ...errors import MedifyError
from ...models import Addendum, NoteApproval
from ...services.features import require_feature
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

    model_config = ConfigDict(from_attributes=True)

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
    auth: DoctorAuth,
    db: DB,
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
    require_feature(db, auth.facility_id, "visit.addendum")
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state not in ("approved", "uploaded"):
        # الملحق لمذكرة معتمدة نهائياً فقط — قبلها التحرير المباشر/Unlock هو المسار
        raise MedifyError("MDF-4223", details={"state": visit.state, "reason": "addendum_requires_approved"})

    # تحقق من وجود اعتماد أصلي (note_approval) — قد تتعدد الصفوف بعد Unlock/النسخ (م5/م6)
    original_approval = db.execute(
        select(NoteApproval).where(NoteApproval.visit_id == visit_id)
        .order_by(NoteApproval.approved_at.desc())
    ).scalars().first()
    if original_approval is None:
        raise MedifyError("MDF-4231", details={"reason": "original_note_approval_missing"})

    # إنشاء ملحق جديد (id يولَّد تلقائياً — UUID v7 من النموذج)
    addendum = Addendum(
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

    # سبب الإضافة قد يحمل تفصيلاً سريرياً — لا يدخل audit_logs (كما في note_unlocks)
    audit(
        db, auth.facility_id, "addendum.created", "addendum", addendum.id, auth.user_id,
        {"visit_id": str(visit_id), "has_reason": bool(payload.reason)},
    )

    # إشعار الدكتور (dr.summary_ready: ملخص جاهز للمراجعة، وهنا ملحق جاهز)
    notify(
        db, auth.facility_id, auth.user_id, "dr.summary_ready",
        {"visit_id": str(visit_id), "addendum_id": str(addendum.id), "type": "addendum"}
    )

    return ok({"addendum": AddendumResponse.model_validate(addendum).model_dump(mode="json")})


@router.get("/visits/{visit_id}/addendums")
async def list_addendums(
    visit_id: uuid.UUID,
    auth: DoctorAuth,
    db: DB,
) -> dict[str, Any]:
    """قائمة الملاحق على زيارة معتمدة.

    تُرجع جميع الملاحق بالترتيب الزمني (الأحدث أولاً).
    """
    get_visit_for_doctor(db, visit_id)  # RLS + وجود الزيارة (MDF-4041)

    addendums = db.execute(
        select(Addendum)
        .where(Addendum.visit_id == visit_id)
        .order_by(Addendum.created_at.desc())
    ).scalars().all()

    return ok({
        "addendums": [
            AddendumResponse.model_validate(a).model_dump(mode="json")
            for a in addendums
        ]
    })


class AddendumApprove(BaseModel):
    """موافقة الدكتور على ملحق (بوابة ① مصغّرة)."""

    pass


@router.patch("/addendums/{addendum_id}/approve")
async def approve_addendum(
    addendum_id: uuid.UUID,
    auth: DoctorAuth,
    db: DB,
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
        raise MedifyError("MDF-4041")

    addendum_visit = get_visit_for_doctor(db, addendum.visit_id)  # RLS + وجود الزيارة

    if addendum.is_approved:
        raise MedifyError("MDF-4223", details={"reason": "addendum_already_approved"})

    # بوابة ① مصغّرة — بصمة محتوى الملحق
    summary_hash = hashlib.sha256(
        str(addendum.content_json).encode()
    ).hexdigest()

    note_approval = NoteApproval(
        visit_id=addendum.visit_id,
        facility_id=auth.facility_id,
        cycle=addendum_visit.cycle,
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

    audit(
        db, auth.facility_id, "addendum.approved", "addendum", addendum.id, auth.user_id,
        {"visit_id": str(addendum.visit_id), "note_approval_id": str(note_approval.id),
         "summary_hash": summary_hash[:12]},
    )

    return ok({"addendum": AddendumResponse.model_validate(addendum).model_dump(mode="json")})
