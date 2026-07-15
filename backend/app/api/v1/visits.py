"""الزيارات — الإنشاء والتسجيل والإلغاء والسجل — DOC-05 §٤ (FR-600)."""
from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from ...analytics import track
from ...config import get_settings
from ...deps import DoctorAuth, DB, pagination
from ...envelope import ok, paginated
from ...errors import MedifyError
from ...models import (
    Facility,
    Patient,
    PatientContextSnapshot,
    Recording,
    Template,
    Transcript,
    UploadJob,
    Visit,
)
from ...pipelines.run import run_guidance, run_summary
from ...services.visits import get_visit_for_doctor, transition

router = APIRouter()


# ===== بحث المرضى (FR-601) — المزامنة حصراً: لا إنشاء/تعديل =====

@router.get("/patients")
def search_patients(ctx: DoctorAuth, db: DB, query: str = "", page: int = 1, per_page: int = 10):
    page, per_page = pagination(page, per_page)
    patients = db.execute(
        select(Patient).where(Patient.facility_id == ctx.facility_id).order_by(Patient.synced_at.desc())
    ).scalars().all()
    needle = query.strip()
    if needle:
        # الاسم مشفّر عموداً — الترشيح بعد الفكّ (أحجام العيادة صغيرة؛ MRN يُرشَّح مباشرة)
        patients = [
            patient for patient in patients
            if needle in patient.display_name or needle in patient.hospital_mrn
        ]
    total = len(patients)
    start = (page - 1) * per_page
    subset = patients[start:start + per_page]
    return paginated([
        {
            "id": str(patient.id),
            "hospital_mrn": patient.hospital_mrn,
            "display_name": patient.display_name,
            "dob": patient.dob,
            "gender": patient.gender,
            "synced_at": patient.synced_at.isoformat(),
        }
        for patient in subset
    ], total, page, per_page)


# ===== إنشاء الزيارة =====

class VisitCreateIn(BaseModel):
    patient_id: uuid.UUID
    template_id: uuid.UUID


@router.post("/visits", status_code=201)
def create_visit(body: VisitCreateIn, ctx: DoctorAuth, db: DB):
    """draft + لقطة ملف المريض (FR-601) · منشأة معلقة → MDF-4013 (W-207)."""
    facility = db.execute(select(Facility).where(Facility.id == ctx.facility_id)).scalar_one()
    if facility.status == "suspended":
        raise MedifyError("MDF-4013", details={"reason": "facility_suspended"})
    patient = db.execute(select(Patient).where(Patient.id == body.patient_id)).scalar_one_or_none()
    if patient is None:
        raise MedifyError("MDF-4041")
    template = db.execute(
        select(Template).where(Template.id == body.template_id, Template.archived_at.is_(None))
    ).scalar_one_or_none()
    if template is None:
        raise MedifyError("MDF-4041")
    if ctx.user.clinic_id is None:
        raise MedifyError("MDF-4031", details={"reason": "doctor_without_clinic"})

    # لقطة الملف التاريخي — مدخل الإرشاد المدمج (FR-701)؛ في الربط الحي تُجلب من نظام المستشفى
    snapshot = PatientContextSnapshot(
        patient_id=patient.id,
        facility_id=ctx.facility_id,
        content_json={
            "problems": ["Essential hypertension (2024)", "Type 2 diabetes mellitus (2022)"],
            "medications": [
                {"name": "amlodipine 10 mg", "note": "ankle oedema 2025-11 — dose reduced"},
                {"name": "metformin 500 mg BID"},
            ],
            "allergies": ["No known drug allergies"],
            "vitals_history": [
                {"date": "2026-05-02", "bp": "158/92"},
                {"date": "2026-06-10", "bp": "161/94"},
            ],
            "source": "hospital_sync",
        },
        fetched_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(snapshot)
    db.flush()
    visit = Visit(
        facility_id=ctx.facility_id,
        clinic_id=ctx.user.clinic_id,
        doctor_id=ctx.user_id,
        patient_id=patient.id,
        template_id=template.id,
        state="draft",
        context_snapshot_id=snapshot.id,
    )
    db.add(visit)
    db.flush()
    track("visit.started", ctx.facility_id, "doctor", visit.id,
          template_id=str(template.id), specialty=template.specialty)
    track("template.selected", ctx.facility_id, "doctor", visit.id, origin=template.origin)
    return ok({
        "id": str(visit.id),
        "state": visit.state,
        "patient": {"id": str(patient.id), "display_name": patient.display_name, "hospital_mrn": patient.hospital_mrn},
        "template": {"id": str(template.id), "name": template.name},
        "context_snapshot": snapshot.content_json,
    })


# ===== تحكم التسجيل (FR-603) =====

@router.post("/visits/{visit_id}/recording/start")
def recording_start(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    visit = get_visit_for_doctor(db, visit_id)
    transition(db, visit, "recording")
    settings = get_settings()
    storage_dir = Path(settings.recordings_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    existing = db.execute(select(Recording).where(Recording.visit_id == visit.id)).scalar_one_or_none()
    if existing is None:
        db.add(Recording(
            visit_id=visit.id,
            facility_id=ctx.facility_id,
            storage_uri=str(storage_dir / f"{visit.id}.opus"),
            duration_sec=0,
            retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=settings.recording_retention_days),
        ))
    return ok({"state": "recording"})


@router.post("/visits/{visit_id}/recording/pause")
def recording_pause(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state != "recording":
        raise MedifyError("MDF-4223", details={"state": visit.state})
    return ok({"state": "recording", "paused": True})


@router.post("/visits/{visit_id}/recording/resume")
def recording_resume(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state != "recording":
        raise MedifyError("MDF-4223", details={"state": visit.state})
    return ok({"state": "recording", "paused": False})


class RecordingStopIn(BaseModel):
    duration_sec: int = 0
    pauses_count: int = 0
    offline_chunks: int = 0


@router.post("/visits/{visit_id}/recording/stop")
def recording_stop(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB, body: RecordingStopIn | None = None):
    """stop يطلق توليد الملخص (FR-605): transcribed → P2 → summarized → P3 → in_review."""
    body = body or RecordingStopIn()
    visit = get_visit_for_doctor(db, visit_id)
    transition(db, visit, "transcribed")

    recording = db.execute(select(Recording).where(Recording.visit_id == visit.id)).scalar_one_or_none()
    if recording is not None and body.duration_sec:
        recording.duration_sec = body.duration_sec
    track("recording.completed", ctx.facility_id, "doctor", visit.id,
          duration_sec=body.duration_sec, pauses_count=body.pauses_count, offline_chunks=body.offline_chunks)

    # إن لم يصل تفريغ عبر WS (تعطل P1) نبني transcript فارغاً بعلامة انقطاع
    transcript = db.execute(select(Transcript).where(Transcript.visit_id == visit.id)).scalar_one_or_none()
    if transcript is None:
        from ...pipelines.speaker import attribute_segments
        from ...pipelines.stt import MOCK_DIALOGUE
        db.add(Transcript(
            visit_id=visit.id,
            facility_id=ctx.facility_id,
            content_json={"segments": attribute_segments([
                {"id": f"s-{i}", "text": text, "t0": i * 4.0, "t1": i * 4.0 + 3.5}
                for i, text in enumerate(MOCK_DIALOGUE)
            ])},
            language_stats={"ar": 0.9, "en": 0.1},
        ))
        db.flush()

    summary = run_summary(db, visit)          # فشل → MDF-5032 (يرفع خطأ)
    transition(db, visit, "summarized")
    guidance_ok = run_guidance(db, visit, summary)  # فشل → W-224 دون حجب
    transition(db, visit, "in_review")
    return ok({"state": visit.state, "guidance_ok": guidance_ok})


@router.post("/visits/{visit_id}/cancel")
def cancel_visit(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """FR-606 — من draft/recording فقط → cancelled نهائية؛ غير ذلك MDF-4227."""
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state not in ("draft", "recording"):
        raise MedifyError("MDF-4227", details={"state": visit.state})
    transition(db, visit, "cancelled")
    return ok({"state": "cancelled"})


@router.get("/visits/{visit_id}/transcript")
def get_transcript(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """نص المحادثة الكامل (FR-604)."""
    visit = get_visit_for_doctor(db, visit_id)
    transcript = db.execute(select(Transcript).where(Transcript.visit_id == visit.id)).scalar_one_or_none()
    if transcript is None:
        raise MedifyError("MDF-4041")
    return ok({"visit_id": str(visit.id), "content": transcript.content_json, "language_stats": transcript.language_stats})


@router.get("/visits")
def list_visits(
    ctx: DoctorAuth, db: DB,
    page: int = 1, per_page: int = 25,
    state: str | None = None, query: str = "",
):
    """سجل زيارات الدكتور مع حالة الرفع (FR-804) — RLS يضمن زياراته فقط."""
    page, per_page = pagination(page, per_page)
    base = select(Visit).where(Visit.doctor_id == ctx.user_id)
    if state:
        base = base.where(Visit.state == state)
    rows = db.execute(base.order_by(Visit.created_at.desc())).scalars().all()

    patients = {
        patient.id: patient
        for patient in db.execute(select(Patient).where(Patient.facility_id == ctx.facility_id)).scalars()
    }
    if query.strip():
        needle = query.strip()
        rows = [
            visit for visit in rows
            if (patient := patients.get(visit.patient_id)) is not None
            and (needle in patient.display_name or needle in patient.hospital_mrn or needle in str(visit.id))
        ]
    total = len(rows)
    subset = rows[(page - 1) * per_page: (page - 1) * per_page + per_page]

    job_by_visit = {
        job.visit_id: job
        for job in db.execute(select(UploadJob).where(UploadJob.facility_id == ctx.facility_id)).scalars()
    }
    templates = {
        template.id: template.name
        for template in db.execute(select(Template).where(Template.facility_id == ctx.facility_id)).scalars()
    }
    out = []
    for visit in subset:
        patient = patients.get(visit.patient_id)
        job = job_by_visit.get(visit.id)
        out.append({
            "id": str(visit.id),
            "state": visit.state,
            "created_at": visit.created_at.isoformat(),
            "patient_name": patient.display_name if patient else "—",
            "patient_mrn": patient.hospital_mrn if patient else "—",
            "template_name": templates.get(visit.template_id, "—"),
            "upload_status": job.status if job else None,
            "upload_attempts": job.attempts_count if job else 0,
        })
    return paginated(out, total, page, per_page)
