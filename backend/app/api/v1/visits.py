"""الزيارات — الإنشاء والتسجيل والإلغاء والسجل — DOC-05 §٤ (FR-600)."""
from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...analytics import track
from ...audit import audit
from ...config import get_settings
from ...deps import Auth, DoctorAuth, DB, pagination
from ...envelope import ok, paginated
from ...errors import MedifyError
from ...models import (
    AuditLog,
    Facility,
    Patient,
    PatientContextSnapshot,
    ProcessingAttempt,
    Recording,
    Template,
    Transcript,
    UploadJob,
    User,
    Visit,
    VisitConsent,
)
from ...services.audio_integrity import verify_finalized_audio
from ...services.consent import consent_document
from ...services.history import build_context
from ...services.processing import (
    attempts_total,
    enqueue_process_visit,
    process_visit_pipeline,
    queue_mode_enabled,
)
from ...services.metrics import record_reopen
from ...services.patient_summary import regenerate_for_new_version
from ...services.pending_queue import pending_for_doctor
from ...services.retention import resolve_retention_days
from ...services.versions import start_reopen_draft
from ...services.visits import get_visit_for_doctor, transition

router = APIRouter()


# ===== المرضى (FR-601) — المزامنة هي المصدر الأساسي + إنشاء يدوي (تعديل مالك 2026-07-26) =====

def _manual_patient_ids(db: Session, facility_id: uuid.UUID) -> set[str]:
    """معرفات المرضى المُنشأين يدوياً — من سجل التدقيق (لا عمود مصدر في DOC-04)."""
    rows = db.execute(
        select(AuditLog.entity_id).where(
            AuditLog.facility_id == facility_id,
            AuditLog.action == "patient.created",
        )
    ).scalars().all()
    return {row for row in rows if row}


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
    manual = _manual_patient_ids(db, ctx.facility_id)
    return paginated([
        {
            "id": str(patient.id),
            "hospital_mrn": patient.hospital_mrn,
            "display_name": patient.display_name,
            "dob": patient.dob,
            "gender": patient.gender,
            "synced_at": patient.synced_at.isoformat(),
            # المصدر يميّز ملف المزامنة عن ملف أنشأه الطبيب يدوياً (MRN غير مؤكد من نظام المستشفى)
            "source": "manual" if str(patient.id) in manual else "hospital_sync",
        }
        for patient in subset
    ], total, page, per_page)


class PatientCreateIn(BaseModel):
    """إنشاء ملف مريض يدوياً — تعديل مالك 2026-07-26 على قرار «المزامنة حصراً»."""

    hospital_mrn: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=2, max_length=120)
    dob: str | None = Field(default=None, max_length=10)      # YYYY-MM-DD
    gender: str | None = Field(default=None, max_length=16)


@router.post("/patients", status_code=201)
def create_patient(body: PatientCreateIn, ctx: DoctorAuth, db: DB):
    """ملف مريض جديد داخل منشأة الطبيب — للمريض الذي لم يصل بعد من مزامنة نظام المستشفى.

    المزامنة تبقى المصدر الأساسي؛ هذا مسار الاستثناء (مريض جديد على العيادة). MRN مكرر
    داخل المنشأة → يُعاد الملف القائم بدل ازدواج يرفضه قيد uq_patients_facility_mrn.
    """
    facility = db.execute(select(Facility).where(Facility.id == ctx.facility_id)).scalar_one()
    if facility.status == "suspended":
        raise MedifyError("MDF-4013", details={"reason": "facility_suspended"})

    mrn = body.hospital_mrn.strip()
    display_name = body.display_name.strip()
    dob = (body.dob or "").strip() or None
    gender = (body.gender or "").strip() or None
    if not mrn or len(display_name) < 2:
        raise MedifyError("MDF-5001", details={"validation": "hospital_mrn/display_name required"})

    existing = db.execute(
        select(Patient).where(Patient.facility_id == ctx.facility_id, Patient.hospital_mrn == mrn)
    ).scalar_one_or_none()
    if existing is not None:
        return ok({
            "id": str(existing.id),
            "hospital_mrn": existing.hospital_mrn,
            "display_name": existing.display_name,
            "dob": existing.dob,
            "gender": existing.gender,
            "synced_at": existing.synced_at.isoformat(),
            "source": "manual" if str(existing.id) in _manual_patient_ids(db, ctx.facility_id) else "hospital_sync",
            "already_exists": True,
        })

    now = dt.datetime.now(dt.timezone.utc)
    patient = Patient(
        facility_id=ctx.facility_id,
        hospital_mrn=mrn,
        display_name=display_name,
        dob=dob,
        gender=gender,
        synced_at=now,  # لا عمود مصدر في DOC-04 — التمييز من سجل التدقيق أدناه
    )
    db.add(patient)
    db.flush()
    # لا محتوى سريرياً ولا اسم مريض في السجل (DOC-16) — MRN معرّف ملف لا محتوى
    audit(db, ctx.facility_id, "patient.created", "patient", patient.id, ctx.user_id,
          {"hospital_mrn": mrn, "source": "manual"})
    return ok({
        "id": str(patient.id),
        "hospital_mrn": patient.hospital_mrn,
        "display_name": patient.display_name,
        "dob": patient.dob,
        "gender": patient.gender,
        "synced_at": patient.synced_at.isoformat(),
        "source": "manual",
        "already_exists": False,
    })


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

    # لقطة الملف التاريخي — مدخل الإرشاد المدمج (FR-701). تُبنى من مراجعات المريض السابقة
    # الفعلية عند هذا الطبيب (تعديل مالك 2026-07-26)؛ في الربط الحي تُدمج معها بيانات المستشفى.
    snapshot = PatientContextSnapshot(
        patient_id=patient.id,
        facility_id=ctx.facility_id,
        content_json=build_context(db, patient.id, ctx.user_id),
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


# ===== بوابة موافقة المريض (A1 — توجيه المالك 2026-07-22) =====

@router.get("/visits/{visit_id}/consent")
def get_consent(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """نص الموافقة ثنائي اللغة + هل وُثِّقت لهذه الزيارة — تعرضه الواجهة قبل أي تسجيل."""
    visit = get_visit_for_doctor(db, visit_id)
    consent = db.execute(select(VisitConsent).where(VisitConsent.visit_id == visit.id)).scalar_one_or_none()
    captured = None
    if consent is not None:
        capturer = db.execute(select(User).where(User.id == consent.captured_by)).scalar_one_or_none()
        captured = {
            "captured_at": consent.captured_at.isoformat(),
            "captured_by": capturer.full_name if capturer else "—",
            "method": consent.method,
            "consent_version": consent.consent_version,
            "text_hash": consent.consent_text_hash,
        }
    return ok({"document": consent_document(), "captured": captured})


class ConsentIn(BaseModel):
    acknowledged: bool
    method: str = "verbal_ack"  # verbal_ack | written


@router.post("/visits/{visit_id}/consent", status_code=201)
def record_consent(visit_id: uuid.UUID, body: ConsentIn, ctx: DoctorAuth, db: DB):
    """توثيق الموافقة — سجل إلحاقي لا يقبل تعديلاً. بدونه يرفض trigger القاعدة بدء التسجيل."""
    visit = get_visit_for_doctor(db, visit_id)
    if not body.acknowledged:
        raise MedifyError("MDF-4230", details={"reason": "not_acknowledged"})
    if body.method not in ("verbal_ack", "written"):
        raise MedifyError("MDF-4041", details={"method": body.method})
    if visit.state != "draft":
        raise MedifyError("MDF-4223", details={"state": visit.state, "reason": "consent_before_recording"})

    existing = db.execute(select(VisitConsent).where(VisitConsent.visit_id == visit.id)).scalar_one_or_none()
    if existing is not None:
        # إلحاقي: لا يُعاد توثيقها ولا تُعدَّل
        return ok({"consent_id": str(existing.id), "captured_at": existing.captured_at.isoformat(),
                   "already_recorded": True})

    document = consent_document()
    consent = VisitConsent(
        visit_id=visit.id,
        facility_id=ctx.facility_id,
        consent_version=document["version"],
        consent_text_hash=document["text_hash"],
        method=body.method,
        captured_by=ctx.user_id,
        captured_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(consent)
    db.flush()
    audit(db, ctx.facility_id, "visit.consent_recorded", "visit", visit.id, ctx.user_id,
          {"consent_version": document["version"], "method": body.method})
    return ok({"consent_id": str(consent.id), "captured_at": consent.captured_at.isoformat(),
               "already_recorded": False})


# ===== تحكم التسجيل (FR-603) =====

@router.post("/visits/{visit_id}/recording/start")
def recording_start(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    visit = get_visit_for_doctor(db, visit_id)
    # الحارس التطبيقي على المسار المشروع فقط (draft→recording)؛ الحالات الأخرى
    # تتركها آلة الحالات لرسالة MDF-4223. الحارس النهائي trigger القاعدة — دفاع بطبقتين.
    if visit.state == "draft":
        consent = db.execute(select(VisitConsent).where(VisitConsent.visit_id == visit.id)).scalar_one_or_none()
        if consent is None:
            raise MedifyError("MDF-4230", details={"visit_id": str(visit.id)})
    transition(db, visit, "recording", ctx.user_id)
    settings = get_settings()
    storage_dir = Path(settings.recordings_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    existing = db.execute(select(Recording).where(Recording.visit_id == visit.id)).scalar_one_or_none()
    if existing is None:
        # م8: الختم من سياسة الاحتفاظ الموحّدة (audio=90 افتراضاً، تجاوز لكل منشأة؛
        # NULL = «بلا حذف» فيُختم أفقاً بعيداً عملياً)
        audio_days = resolve_retention_days(db, ctx.facility_id, "audio")
        if audio_days is None:
            audio_days = 36500
        db.add(Recording(
            visit_id=visit.id,
            facility_id=ctx.facility_id,
            storage_uri=str(storage_dir / f"{visit.id}.wav"),  # PCM16 من المتصفح يُحفظ WAV
            duration_sec=0,
            retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=audio_days),
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
    """stop يطلق المعالجة فوراً (FR-605 + قرار مالك 2026-08-02 + المرحلة 3):
    inline (بلا Redis): P1→P2→P3 داخل الطلب كما كان · queue (النشر): مهمة arq
    والواجهة تستطلع processing-status — المعالجة تبدأ فوراً في الحالتين، لا تأجيل."""
    body = body or RecordingStopIn()
    visit = get_visit_for_doctor(db, visit_id)
    # finalize صارم (المرحلة 2): لا-فجوات + حجم + bit-exact مقابل سجل المقاطع —
    # فشله = MDF-4234 والزيارة تبقى recording ليعيد العميل المزامنة ثم المحاولة
    verify_finalized_audio(db, visit)
    transition(db, visit, "transcribed", ctx.user_id)

    recording = db.execute(select(Recording).where(Recording.visit_id == visit.id)).scalar_one_or_none()
    if recording is not None and body.duration_sec:
        recording.duration_sec = body.duration_sec
    track("recording.completed", ctx.facility_id, "doctor", visit.id,
          duration_sec=body.duration_sec, pauses_count=body.pauses_count, offline_chunks=body.offline_chunks)

    if queue_mode_enabled():
        db.flush()
        db.commit()  # الحالة transcribed تُثبَّت قبل الإدراج — العامل يقرأها من جلسة أخرى
        enqueue_process_visit(visit.id)
        return ok({"state": visit.state, "processing": "queued"})

    guidance_ok = process_visit_pipeline(db, visit, ctx.user_id)
    return ok({"state": visit.state, "guidance_ok": guidance_ok})


@router.get("/visits/{visit_id}/processing-status")
def processing_status(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """حالة المعالجة للاستطلاع (المرحلة 3) — آخر محاولة لكل تشغيل + حكم الفشل النهائي."""
    visit = get_visit_for_doctor(db, visit_id)
    last = db.execute(
        select(ProcessingAttempt)
        .where(ProcessingAttempt.visit_id == visit.id)
        .order_by(ProcessingAttempt.started_at.desc(), ProcessingAttempt.id.desc())
    ).scalars().first()
    total = attempts_total()
    failed_final = (
        last is not None and not last.succeeded
        and (last.error_class == "non_retryable" or last.attempt_no >= total)
        and visit.state in ("recording", "transcribed")
    )
    return ok({
        "state": visit.state,
        "failed_final": failed_final,
        "attempts_total": total,
        "last_attempt": None if last is None else {
            "stage": last.stage,
            "attempt_no": last.attempt_no,
            "error_class": last.error_class,
            "succeeded": last.succeeded,
            "finished_at": last.finished_at.isoformat(),
        },
    })


@router.post("/visits/{visit_id}/reprocess")
def reprocess_visit(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """إعادة معالجة زيارة توقفت بعد فشل نهائي (المرحلة 3) — من transcribed حصراً.

    inline يعالج داخل الطلب؛ queue يعيد الإدراج. المراحل المكتملة تُتخطى (idempotent).
    """
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state != "transcribed":
        raise MedifyError("MDF-4223", details={"state": visit.state, "action": "reprocess"})
    audit(db, ctx.facility_id, "visit.reprocess_requested", "visit", visit.id, ctx.user_id)
    if queue_mode_enabled():
        enqueue_process_visit(visit.id)
        return ok({"state": visit.state, "processing": "queued"})
    guidance_ok = process_visit_pipeline(db, visit, ctx.user_id)
    return ok({"state": visit.state, "guidance_ok": guidance_ok})


@router.post("/visits/{visit_id}/cancel")
def cancel_visit(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """FR-606 — من draft/recording فقط → cancelled نهائية؛ غير ذلك MDF-4227."""
    visit = get_visit_for_doctor(db, visit_id)
    if visit.state not in ("draft", "recording"):
        raise MedifyError("MDF-4227", details={"state": visit.state})
    transition(db, visit, "cancelled", ctx.user_id)
    return ok({"state": "cancelled"})


# ===== الإبطال Void (قرار مالك 2026-08-03 — موسَّع بمهمة التحصين م4) =====

VoidReason = Literal["wrong_patient", "duplicate", "test_recording", "test", "consent_withdrawn", "other"]
# المصادر: summarized (قبل المراجعة) · in_review · approved قبل النقل (= codes_approved
# بخريطة أسماء التوجيه، وnote_approved ضمن in_review). من uploaded وما بعدها → 409 (المسار reopen).
VOIDABLE_STATES = ("summarized", "in_review", "approved")


class VoidIn(BaseModel):
    reason: VoidReason  # قيمة خارج القائمة = 422 بمغلف التحقق القياسي
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _other_requires_note(self) -> "VoidIn":
        if self.reason == "other" and not self.note.strip():
            raise ValueError("reason=other يتطلب توضيحاً نصياً في note")
        return self


@router.post("/visits/{visit_id}/void")
def void_visit(visit_id: uuid.UUID, body: VoidIn, ctx: Auth, db: DB):
    """إبطال زيارة لا يصح اعتمادها — من summarized/in_review/approved (قبل النقل) → voided نهائية.

    RBAC (م4): صاحب الزيارة (RLS يضمن الملكية) أو أدمن المنشأة (سياسة doctor_scope
    تمرّره — لا يقرأ محتوى سريرياً، والإبطال فعل إداري على الحالة).
    Void ≠ Delete: المحتوى السريري يُختم ويخرج من المخارج (410) والإحصائيات، بينما
    واقعة الإبطال (الفاعل/السبب/الوقت) تُدوَّن في سجل التدقيق الإلحاقي وتبقى.
    الصوت لا يُمس هنا — يتبع سياسة الاحتفاظ (المُبطلة على أقصر مدة — م8).
    """
    visit = get_visit_for_doctor(db, visit_id)
    reason = "test_recording" if body.reason == "test" else body.reason  # توافق عكسي للاسم القديم
    note = body.note.strip()
    from_state = visit.state
    if from_state not in VOIDABLE_STATES:
        # قبل المعالجة مساره «إلغاء» (FR-606)؛ بعد النقل المسار reopen — الحكم النهائي للـtrigger
        raise MedifyError("MDF-4223", details={"state": from_state, "to": "voided"})
    transition(db, visit, "voided", ctx.user_id)
    # سبب الإبطال بيان إداري لا محتوى سريرياً (DOC-16) — يُدوَّن كاملاً مع هوية الفاعل والوقت
    audit(db, ctx.facility_id, "visit.voided", "visit", visit.id, ctx.user_id,
          {"reason": reason, "note": note, "from_state": from_state, "actor_role": ctx.role})
    return ok({"state": "voided", "reason": reason})


# ===== طابور «بانتظارك» (م16) =====

@router.get("/physicians/me/pending")
def my_pending_queue(ctx: DoctorAuth, db: DB):
    """أربع مجموعات بعمر كل بند وترتيب بالأقدم — المُبطلة لا تظهر (خارج in_review)."""
    return ok(pending_for_doctor(db, ctx.user_id))


# ===== إعادة الفتح Reopen (م6) — نسخة جديدة ببوابتين =====

class ReopenIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/visits/{visit_id}/reopen")
def reopen_visit(visit_id: uuid.UUID, body: ReopenIn, ctx: DoctorAuth, db: DB):
    """المبدأ 2: التعديل بعد النقل = reopen حصراً — من uploaded فقط، بسبب إلزامي.

    الأثر: uploaded → reopened → in_review، دورة جديدة (cycle+1)، مسودة نسخة v+1
    منسوخة من آخر منقولة (سبب الفتح مشفّر معها)، وإعادة البوابتين إلزامية —
    ① بنقرة إن لم يتغيّر النص (مقارنة hash — م5)، و② كاملة دائماً.
    يقابله /upload-retry: نفس النسخة بلا بوابات (عطل تقني لا قرار سريري).
    """
    visit = get_visit_for_doctor(db, visit_id)
    reason = body.reason.strip()
    if not reason:
        raise MedifyError("MDF-4225", details={"missing": "reason"})
    if visit.state != "uploaded":
        raise MedifyError("MDF-4223", details={"state": visit.state, "action": "reopen"})

    transition(db, visit, "reopened", ctx.user_id)
    visit.cycle += 1  # بوابتا الدورة الجديدة مستقلتان — triggers 0014 واعية بالدورة
    db.flush()
    draft = start_reopen_draft(db, visit, reason)
    regenerate_for_new_version(db, visit)  # م14: النسخة الجديدة بلا ملخص حتى بوابتها ①
    record_reopen(db, visit, draft.version_number)  # م15: reopen_rate
    transition(db, visit, "in_review", ctx.user_id)
    # السبب محتوى سريري محتمل — مكانه note_versions المشفّر؛ التدقيق يحمل المرجع والأرقام
    audit(db, ctx.facility_id, "visit.reopened", "visit", visit.id, ctx.user_id,
          {"new_version": draft.version_number, "draft_version_id": str(draft.id)})
    return ok({"state": visit.state, "version": draft.version_number})


# ===== تشغيل الصوت للسند (م10) — HTTP Range + مصادقة عبر ?token= (وسم <audio> لا يحمل ترويسات) =====

_AUDIO_MEDIA = {".wav": "audio/wav", ".flac": "audio/flac"}


@router.get("/visits/{visit_id}/audio")
def visit_audio(visit_id: uuid.UUID, request: Request, token: str = ""):
    """بث ملف صوت الزيارة بدعم Range — للقفز الدقيق (±1ث) في مشغّل السند.

    المصادقة كقناة WS: access token في الاستعلام (المتصفح لا يمرر Authorization
    لوسم audio). RLS يضمن أن الدكتور لا يصل غير زياراته (MDF-4041 بلا كشف وجود).
    """
    from ...db import rls_session
    from ...security import decode_token

    try:
        payload = decode_token(token, "access")
    except Exception:
        raise MedifyError("MDF-4012")
    if payload.get("role") != "doctor":
        raise MedifyError("MDF-4031")

    with rls_session(payload["facility_id"], payload["sub"], "doctor") as adb:
        visit = adb.execute(select(Visit).where(Visit.id == visit_id)).scalar_one_or_none()
        if visit is None:
            raise MedifyError("MDF-4041")
        recording = adb.execute(
            select(Recording).where(Recording.visit_id == visit_id)
        ).scalar_one_or_none()
        if recording is None or recording.deleted_at is not None:
            raise MedifyError("MDF-4041")
        storage_uri = recording.storage_uri

    path = Path(storage_uri)
    if not path.exists():
        raise MedifyError("MDF-4041")
    media_type = _AUDIO_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    file_size = path.stat().st_size

    range_header = request.headers.get("Range", "")
    if range_header.startswith("bytes="):
        try:
            start_s, _, end_s = range_header[6:].partition("-")
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else file_size - 1
        except ValueError:
            start, end = 0, file_size - 1
        end = min(end, file_size - 1)
        if start > end or start >= file_size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        with path.open("rb") as handle:
            handle.seek(start)
            chunk = handle.read(end - start + 1)
        return Response(
            content=chunk,
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
            },
        )

    return Response(
        content=path.read_bytes(),
        media_type=media_type,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
    )


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
