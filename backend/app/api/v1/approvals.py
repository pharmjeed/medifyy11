"""الاعتماد والرفع — DOC-05 §٤ (FR-800): /approve هو المسار الوحيد الذي يُنشئ upload_job."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ...analytics import track
from ...audit import audit
from ...deps import DoctorAuth, DB
from ...envelope import ok
from ...errors import MedifyError
from ...models import (
    Approval,
    GuidanceItem,
    NoteApproval,
    NoteUnlock,
    Summary,
    SummarySection,
    UploadAttempt,
    UploadJob,
)
from ...services.claim_readiness import blocking_findings
from ...services.code_registry import check_code, registry_systems
from ...services.fhir import build_bundle, store_bundle
from ...services.metrics import record_approval_metrics
from ...services.uploader import process_upload_job
from ...services.versions import finalize_version
from ...services.visits import active_note_approval, get_visit_for_doctor, summary_hashes, transition

router = APIRouter()


@router.post("/visits/{visit_id}/note-approve")
def note_approve_visit(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """البوابة ① — اعتماد نص المذكرة (توجيه المالك 2026-07-22).

    بعدها يتجمّد نص المذكرة (trigger القاعدة) ويبقى حسم الأكواد مفتوحاً للبوابة ②.
    بعد Unlock (قرار مالك 2026-08-03) تُنشئ إعادة الاعتماد صفاً جديداً ببصمة النص المعدَّل.
    """
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state != "in_review":
        raise MedifyError("MDF-4223", details={"state": visit.state})
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    if summary is None:
        raise MedifyError("MDF-4041")

    existing = active_note_approval(db, visit)
    if existing is not None:
        return ok({
            "note_approved": True,
            "note_approval_id": str(existing.id),
            "approved_at": existing.approved_at.isoformat(),
            "summary_hash": existing.summary_hash,
            "already_approved": True,
        })

    content_hash, _codes_hash = summary_hashes(db, visit)
    note_approval = NoteApproval(
        visit_id=visit.id,
        facility_id=ctx.facility_id,
        cycle=visit.cycle,
        approved_by=ctx.user_id,
        approved_at=dt.datetime.now(dt.timezone.utc),
        summary_hash=content_hash,
    )
    db.add(note_approval)
    db.flush()
    prior_unlocks = db.execute(
        select(func.count(NoteUnlock.id)).where(NoteUnlock.visit_id == visit.id)
    ).scalar_one()
    audit(db, ctx.facility_id, "visit.note_approved", "visit", visit.id, ctx.user_id,
          {"gate": 1, "summary_hash": content_hash[:12],
           "reapproval_after_unlock": prior_unlocks > 0})
    review_ms = int((note_approval.approved_at - summary.generated_at).total_seconds() * 1000)
    track("visit.note_approved", ctx.facility_id, "doctor", visit.id, review_ms=review_ms)
    return ok({
        "note_approved": True,
        "note_approval_id": str(note_approval.id),
        "approved_at": note_approval.approved_at.isoformat(),
        "summary_hash": content_hash,
        "already_approved": False,
    })


class NoteUnlockIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/visits/{visit_id}/note-unlock")
def note_unlock_visit(visit_id: uuid.UUID, body: NoteUnlockIn, ctx: DoctorAuth, db: DB):
    """فتح المذكرة — نقض البوابة ① قبل إتمام ② (قرار مالك 2026-08-03، حلقة CDI).

    مراجعة الأكواد تكشف نقص توثيق (جهة الإصابة، مع/بدون مضاعفات…) والنص مجمّد — بدل اعتماد
    كود بلا سند أو كود أقل تحديداً: نقض إلحاقي بسبب مسجّل، ثم تعديل، ثم إعادة اعتماد ①.
    قرارات الأكواد المحسومة تبقى كما هي. بعد البوابة ② المسار Addendum حصراً (trigger القاعدة
    يرفض النقض بعدها حتى لو تجاوز التطبيق).
    """
    visit = get_visit_for_doctor(db, visit_id)
    reason = body.reason.strip()
    if not reason:
        raise MedifyError("MDF-4225", details={"missing": "reason"})
    # حاجزا Unlock البنيويان → MDF-4236 (م5): بعد ② المسار Addendum، وبعد النقل المسار Reopen
    if visit.state != "in_review":
        raise MedifyError("MDF-4236", details={"state": visit.state, "after_final_approval": "addendum"})
    # م6: الحاجز بدورة النسخة الحالية — بوابة ② لدورة منقولة سابقة لا تمنع unlock الدورة الجديدة
    approval = db.execute(
        select(Approval).where(Approval.visit_id == visit.id, Approval.cycle == visit.cycle)
    ).scalar_one_or_none()
    if approval is not None:
        raise MedifyError("MDF-4236", details={"reason": "gate2_completed", "path": "addendum"})
    note_approval = active_note_approval(db, visit)
    if note_approval is None:
        raise MedifyError("MDF-4231", details={"reason": "nothing_to_unlock"})

    unlock = NoteUnlock(
        visit_id=visit.id,
        facility_id=ctx.facility_id,
        note_approval_id=note_approval.id,
        reason=reason,
        unlocked_by=ctx.user_id,
        unlocked_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(unlock)
    db.flush()
    # السبب النصي (محتوى سريري محتمل) يبقى في note_unlocks المشفّر — سجل التدقيق يحمل المرجع لا النص
    audit(db, ctx.facility_id, "visit.note_unlocked", "visit", visit.id, ctx.user_id,
          {"gate": 1, "note_approval_id": str(note_approval.id), "note_unlock_id": str(unlock.id),
           "revoked_summary_hash": note_approval.summary_hash[:12]})
    return ok({
        "note_unlocked": True,
        "note_unlock_id": str(unlock.id),
        "note_approval_id": str(note_approval.id),
        "unlocked_at": unlock.unlocked_at.isoformat(),
        "state": visit.state,
    })


@router.post("/visits/{visit_id}/approve")
def approve_visit(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """البوابة ② — اعتماد الأكواد (FR-801).

    لا تُقبل قبل البوابة ① (MDF-4231 تطبيقياً، ومفتاح أجنبي NOT NULL في القاعدة)،
    ولا مع إرشادات معلقة (MDF-4222) ولا مع كود ينتظر إدخال الطبيب.
    ثم تنشئ upload_job (FR-802) — ولا خروج بيانات قبلها.
    """
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state != "in_review":
        raise MedifyError("MDF-4223", details={"state": visit.state})

    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    if summary is None:
        raise MedifyError("MDF-4041")

    # النشط فقط — اعتماد ① منقوض بمسار Unlock لا يمرّر البوابة ② (قرار مالك 2026-08-03)
    note_approval = active_note_approval(db, visit)
    if note_approval is None:
        raise MedifyError("MDF-4231", details={"visit_id": str(visit.id)})

    pending = db.execute(
        select(func.count(GuidanceItem.id))
        .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
        .where(SummarySection.summary_id == summary.id, GuidanceItem.status == "pending")
    ).scalar_one()
    if pending > 0:
        raise MedifyError("MDF-4222", details={"pending_count": pending})

    # «لا تخمين»: بند محسوم بكود محجوب دون العتبة لا يمر إلا بإدخال الطبيب
    awaiting_input = db.execute(
        select(func.count(GuidanceItem.id))
        .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
        .where(
            SummarySection.summary_id == summary.id,
            GuidanceItem.status.in_(["accepted", "modified"]),
            GuidanceItem.requires_doctor_input.is_(True),
            GuidanceItem.code_value.is_(None),
        )
    ).scalar_one()
    if awaiting_input > 0:
        raise MedifyError("MDF-4222", details={"awaiting_doctor_input": awaiting_input,
                                               "reason": "codes_below_confidence_threshold"})

    # البوابة المرجعية (قرار مالك 2026-08-02): كود محسوم غير موجود/ملغى في السجل لا يمر —
    # هذا هو «يُتحقق منه مقابل النظام النشط قبل الرفع» فعلياً. سجل فارغ لنظامٍ ما = لا تحقق له.
    systems_loaded = registry_systems(db)
    if systems_loaded:
        resolved = db.execute(
            select(GuidanceItem)
            .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
            .where(
                SummarySection.summary_id == summary.id,
                GuidanceItem.status.in_(["accepted", "modified"]),
                GuidanceItem.code_value.is_not(None),
            )
        ).scalars().all()
        invalid_codes = []
        for gi in resolved:
            for code_system, code_value in (
                (gi.code_system, gi.code_value),
                (gi.code_secondary_system, gi.code_secondary_value),
            ):
                verdict, entry = check_code(db, code_system, code_value, systems_loaded)
                if verdict in ("unknown", "inactive"):
                    invalid_codes.append({
                        "item_id": str(gi.id),
                        "code_system": code_system,
                        "code_value": code_value,
                        "registry_status": verdict,
                        "replaced_by": entry.replaced_by if entry else None,
                    })
        if invalid_codes:
            raise MedifyError("MDF-4233", details={"items": invalid_codes})

    # م12: محرك جاهزية المطالبة — أي block غير محسوم يمنع الاعتماد (نمط MDF-4222)
    blocks = blocking_findings(db, visit)
    first_pass = not blocks  # نسبة العبور من أول فحص → telemetry
    if blocks:
        raise MedifyError("MDF-4237", details={"findings": blocks})

    content_hash, codes_hash = summary_hashes(db, visit)
    approval = Approval(
        visit_id=visit.id,
        facility_id=ctx.facility_id,
        cycle=visit.cycle,
        note_approval_id=note_approval.id,
        approved_by=ctx.user_id,
        approved_at=dt.datetime.now(dt.timezone.utc),
        summary_hash=content_hash,
        codes_hash=codes_hash,
    )
    db.add(approval)
    db.flush()  # الاعتماد أولاً — قيد FK على upload_jobs يفرض الترتيب
    transition(db, visit, "approved", ctx.user_id)

    # م6: الحزمة بدلالة النسخة (amended + relatesTo للنسخ ≥2) + لقطة note_versions المكتملة
    bundle = build_bundle(db, visit, visit.cycle)
    payload_ref = store_bundle(visit.id, bundle, visit.cycle)
    version_row = finalize_version(db, visit, note_approval, approval, bundle)
    if version_row.version_number > 1 and version_row.diff_json is not None:
        # الـdiff الكامل مشفّر مع النسخة — سجل التدقيق يحمل الأعداد فقط (لا PHI)
        audit(db, ctx.facility_id, "visit.version_diff", "note_version", version_row.id, ctx.user_id,
              version_row.diff_json.get("counts", {}))
    job = UploadJob(
        visit_id=visit.id,
        facility_id=ctx.facility_id,
        approval_id=approval.id,
        idempotency_key=f"{visit.id}:{visit.cycle}",  # م7: retry نفس المفتاح؛ نسخة جديدة مفتاح جديد
        fhir_payload_ref=payload_ref,
        status="queued",
        attempts_count=0,
    )
    db.add(job)
    db.flush()

    audit(db, ctx.facility_id, "visit.approved", "visit", visit.id, ctx.user_id,
          {"gate": 2, "summary_hash": content_hash[:12], "codes_hash": codes_hash[:12],
           "note_approval_id": str(note_approval.id), "version": version_row.version_number})
    review_ms = int((approval.approved_at - summary.generated_at).total_seconds() * 1000)
    edits_count = db.execute(
        select(func.count(SummarySection.id)).where(
            SummarySection.summary_id == summary.id,
            SummarySection.content_current != SummarySection.content_original,
        )
    ).scalar_one()
    track("visit.approved", ctx.facility_id, "doctor", visit.id, review_ms=review_ms,
          edits_count=edits_count, claim_readiness_first_pass=1 if first_pass else 0)
    # م15: مقاييس الزيارة المعمَّرة (edit_distance/الأزمنة/نسب P3/الجاهزية) — أرقام فقط
    record_approval_metrics(db, visit, review_ms=review_ms, claim_readiness_first_pass=first_pass)

    # الرفع الفوري (FR-802) — محاولات آلية ثم إشعارات فشل نهائي
    process_upload_job(db, job.id)
    db.flush()
    refreshed = db.execute(select(UploadJob).where(UploadJob.id == job.id)).scalar_one()
    return ok({
        "approved": True,
        "approval_id": str(approval.id),
        "upload": {"job_id": str(job.id), "status": refreshed.status, "attempts": refreshed.attempts_count},
        "state": visit.state,
    })


@router.get("/visits/{visit_id}/upload-status")
def upload_status(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """حالة الرفع ومحاولاته (FR-805) — W-219."""
    visit = get_visit_for_doctor(db, visit_id)
    # م6: مهمة لكل نسخة — الحالة المعروضة لأحدث مهمة (النسخة الحالية)
    job = db.execute(
        select(UploadJob).where(UploadJob.visit_id == visit.id)
        .order_by(UploadJob.created_at.desc(), UploadJob.id.desc())
    ).scalars().first()
    if job is None:
        raise MedifyError("MDF-4041")
    attempts = db.execute(
        select(UploadAttempt).where(UploadAttempt.job_id == job.id).order_by(UploadAttempt.started_at)
    ).scalars().all()
    return ok({
        "visit_id": str(visit.id),
        "state": visit.state,
        "status": job.status,
        "attempts_count": job.attempts_count,
        "attempts": [
            {
                "started_at": attempt.started_at.isoformat(),
                "result": attempt.result,
                "error_code": attempt.error_code,
            }
            for attempt in attempts
        ],
    })


@router.post("/visits/{visit_id}/upload-retry")
def upload_retry(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """retry-upload (م6): من upload_failed — نفس النسخة والمهمة، بلا بوابات (عطل تقني).

    يقابله reopen: نسخة جديدة ببوابتين (قرار سريري) — الفصل صارم بين المسارين.
    """
    visit = get_visit_for_doctor(db, visit_id)
    job = db.execute(
        select(UploadJob).where(UploadJob.visit_id == visit.id)
        .order_by(UploadJob.created_at.desc(), UploadJob.id.desc())
    ).scalars().first()
    if job is None:
        raise MedifyError("MDF-4041")
    if job.status != "failed":
        raise MedifyError("MDF-4223", details={"upload_status": job.status})
    process_upload_job(db, job.id, manual=True)
    db.flush()
    refreshed = db.execute(select(UploadJob).where(UploadJob.id == job.id)).scalar_one()
    audit(db, ctx.facility_id, "upload.manual_retry", "upload_job", job.id, ctx.user_id)
    return ok({"status": refreshed.status, "attempts_count": refreshed.attempts_count})
