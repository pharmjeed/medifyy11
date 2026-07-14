"""الاعتماد والرفع — DOC-05 §٤ (FR-800): /approve هو المسار الوحيد الذي يُنشئ upload_job."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from ...analytics import track
from ...audit import audit
from ...deps import DoctorAuth, DB
from ...envelope import ok
from ...errors import MedifyError
from ...models import Approval, GuidanceItem, Summary, SummarySection, UploadAttempt, UploadJob
from ...services.fhir import build_bundle, store_bundle
from ...services.uploader import process_upload_job
from ...services.visits import get_visit_for_doctor, summary_hashes, transition

router = APIRouter()


@router.post("/visits/{visit_id}/approve")
def approve_visit(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """البوابة النهائية (FR-801): إرشادات معلقة → MDF-4222 · ينشئ approval ثم upload_job (FR-802)."""
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state != "in_review":
        raise MedifyError("MDF-4223", details={"state": visit.state})

    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    if summary is None:
        raise MedifyError("MDF-4041")
    pending = db.execute(
        select(func.count(GuidanceItem.id))
        .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
        .where(SummarySection.summary_id == summary.id, GuidanceItem.status == "pending")
    ).scalar_one()
    if pending > 0:
        raise MedifyError("MDF-4222", details={"pending_count": pending})

    content_hash, codes_hash = summary_hashes(db, visit)
    approval = Approval(
        visit_id=visit.id,
        facility_id=ctx.facility_id,
        approved_by=ctx.user_id,
        approved_at=dt.datetime.now(dt.timezone.utc),
        summary_hash=content_hash,
        codes_hash=codes_hash,
    )
    db.add(approval)
    db.flush()  # الاعتماد أولاً — قيد FK على upload_jobs يفرض الترتيب
    transition(db, visit, "approved")

    bundle = build_bundle(db, visit)
    payload_ref = store_bundle(visit.id, bundle)
    job = UploadJob(
        visit_id=visit.id,
        facility_id=ctx.facility_id,
        fhir_payload_ref=payload_ref,
        status="queued",
        attempts_count=0,
    )
    db.add(job)
    db.flush()

    audit(db, ctx.facility_id, "visit.approved", "visit", visit.id, ctx.user_id,
          {"summary_hash": content_hash[:12], "codes_hash": codes_hash[:12]})
    review_ms = int((approval.approved_at - summary.generated_at).total_seconds() * 1000)
    edits_count = db.execute(
        select(func.count(SummarySection.id)).where(
            SummarySection.summary_id == summary.id,
            SummarySection.content_current != SummarySection.content_original,
        )
    ).scalar_one()
    track("visit.approved", ctx.facility_id, "doctor", visit.id, review_ms=review_ms, edits_count=edits_count)

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
    job = db.execute(select(UploadJob).where(UploadJob.visit_id == visit.id)).scalar_one_or_none()
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
    """إعادة محاولة يدوية بعد فشل نهائي — للدكتور لزياراته (DOC-06)."""
    visit = get_visit_for_doctor(db, visit_id)
    job = db.execute(select(UploadJob).where(UploadJob.visit_id == visit.id)).scalar_one_or_none()
    if job is None:
        raise MedifyError("MDF-4041")
    if job.status != "failed":
        raise MedifyError("MDF-4223", details={"upload_status": job.status})
    process_upload_job(db, job.id, manual=True)
    db.flush()
    refreshed = db.execute(select(UploadJob).where(UploadJob.id == job.id)).scalar_one()
    audit(db, ctx.facility_id, "upload.manual_retry", "upload_job", job.id, ctx.user_id)
    return ok({"status": refreshed.status, "attempts_count": refreshed.attempts_count})
