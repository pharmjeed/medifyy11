"""عامل الرفع لنظام المستشفى — INTEGRATION_ENGINE=mock|http|hl7 + إعادة محاولة آلية (FR-805).

م6: mock/http يرسلان حزمة FHIR (transaction) · hl7 يرسل MDM عبر MLLP (T02 أول
نقل، T09 استبدال النسخ ≥2) — وكل نتيجة تُختم على صف النسخة في note_versions.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import track
from ..audit import audit
from ..config import get_settings
from ..models import Approval, IntegrationConfig, Patient, UploadAttempt, UploadJob, User, Visit
from ..notify import notify, notify_admins
from .fhir import medify_doc_identifier
from .hl7 import build_mdm, parse_mllp_target, send_mllp
from .versions import get_version, mark_version_upload_result
from .visits import transition

logger = logging.getLogger("medify.uploader")


class UploadOutcome:
    def __init__(self, ok: bool, error_code: str | None = None):
        self.ok = ok
        self.error_code = error_code


def _send_bundle(config: IntegrationConfig | None, payload_ref: str | None) -> UploadOutcome:
    s = get_settings()
    if s.integration_engine == "mock" or config is None or not config.endpoint_url:
        # وجهة وهمية: تنجح دائماً إلا إذا احتوى العنوان مؤشر فشل (للاختبارات)
        endpoint = (config.endpoint_url if config else "") or ""
        if "fail-validation" in endpoint:
            return UploadOutcome(False, "MDF-5051")
        if "fail-unreachable" in endpoint:
            return UploadOutcome(False, "MDF-5052")
        return UploadOutcome(True)
    try:
        with open(payload_ref or "", "r", encoding="utf-8") as handle:
            body = handle.read()
        response = httpx.post(
            config.endpoint_url,
            content=body,
            headers={
                "Content-Type": "application/fhir+json",
                "Authorization": f"Bearer {config.auth_secret_encrypted or ''}",
            },
            timeout=30,
        )
        if response.status_code in (200, 201, 202):
            return UploadOutcome(True)
        if 400 <= response.status_code < 500:
            return UploadOutcome(False, "MDF-5051")
        return UploadOutcome(False, "MDF-5052")
    except httpx.HTTPError:
        return UploadOutcome(False, "MDF-5052")


def _send_hl7(db: Session, config: IntegrationConfig | None, visit: Visit, version_number: int) -> UploadOutcome:
    """MDM عبر MLLP (م6): T02 لأول نسخة، T09 للاستبدال — TXA-13 = وثيقة Medify السابقة حصراً."""
    version_row = get_version(db, visit.id, version_number)
    if version_row is None:
        return UploadOutcome(False, "MDF-5051")
    sections = (version_row.note_snapshot or {}).get("sections", [])
    note_text = "\n".join(f"[{s.get('section_key', '')}] {s.get('content', '')}" for s in sections)
    patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one()
    doctor = db.execute(select(User).where(User.id == visit.doctor_id)).scalar_one_or_none()
    message = build_mdm(
        control_id=f"{visit.id}:{version_number}",  # MSH-10 — مفتاح idempotency الواعي بالنسخة (م7)
        event="T02" if version_number <= 1 else "T09",
        patient_mrn=patient.hospital_mrn,
        patient_name=patient.display_name,
        doctor_name=(doctor.full_name if doctor is not None else ""),
        doc_identifier=medify_doc_identifier(visit.id, version_number),
        parent_doc_identifier=(
            medify_doc_identifier(visit.id, version_number - 1) if version_number > 1 else None
        ),
        note_text=note_text,
    )
    if config is None or not config.endpoint_url:
        return UploadOutcome(False, "MDF-5052")
    try:
        host, port = parse_mllp_target(config.endpoint_url)
        delivered, ack = send_mllp(host, port, message)
        if delivered:
            return UploadOutcome(True)
        return UploadOutcome(False, "MDF-5051" if ack in ("AE", "AR") else "MDF-5052")
    except (OSError, ValueError):
        return UploadOutcome(False, "MDF-5052")


def process_upload_job(db: Session, job_id: uuid.UUID, manual: bool = False) -> None:
    """محاولات آلية حتى الحد ثم فشل نهائي بإشعارات dr/ad.upload_failed — تعمل بمحرك النظام (D-19)."""
    s = get_settings()
    job = db.execute(select(UploadJob).where(UploadJob.id == job_id)).scalar_one_or_none()
    if job is None or job.status == "confirmed":
        return
    visit = db.execute(select(Visit).where(Visit.id == job.visit_id)).scalar_one()
    config = db.execute(
        select(IntegrationConfig).where(IntegrationConfig.facility_id == job.facility_id)
    ).scalar_one_or_none()
    # م6: نسخة المهمة من اعتمادها — نتيجة الرفع تُختم على صفها في note_versions
    approval = db.execute(select(Approval).where(Approval.id == job.approval_id)).scalar_one()
    version_number = approval.cycle

    max_attempts = 1 if manual else s.upload_max_auto_attempts
    outcome = UploadOutcome(False, "MDF-5052")
    for _ in range(max_attempts):
        job.status = "sent"
        job.attempts_count += 1
        if s.integration_engine == "hl7":
            outcome = _send_hl7(db, config, visit, version_number)
        else:
            outcome = _send_bundle(config, job.fhir_payload_ref)
        db.add(
            UploadAttempt(
                job_id=job.id,
                started_at=dt.datetime.now(dt.timezone.utc),
                result="confirmed" if outcome.ok else "failed",
                error_code=outcome.error_code,
            )
        )
        db.flush()
        if outcome.ok or outcome.error_code == "MDF-5051":
            break  # الرفض البنيوي لا يُعاد آلياً — يحتاج تدخلاً

    if outcome.ok:
        job.status = "confirmed"
        transition(db, visit, "uploaded")  # فاعل النظام — Audit موحّد للانتقال (المرحلة 1)
        mark_version_upload_result(db, visit.id, version_number, ok=True)  # النسخة تتجمد للأبد
        db.flush()
        notify(db, job.facility_id, visit.doctor_id, "dr.upload_success", {"visit_id": str(visit.id)})
        audit(db, job.facility_id, "upload.confirmed", "upload_job", job.id, None,
              {"attempts": job.attempts_count, "version": version_number})
    else:
        job.status = "failed"
        if visit.state == "approved":
            transition(db, visit, "upload_failed")  # فاعل النظام
        mark_version_upload_result(db, visit.id, version_number, ok=False)
        db.flush()
        notify(db, job.facility_id, visit.doctor_id, "dr.upload_failed",
               {"visit_id": str(visit.id), "mdf": outcome.error_code})
        notify_admins(db, job.facility_id, "ad.upload_failed",
                      {"visit_id": str(visit.id), "mdf": outcome.error_code})
        audit(db, job.facility_id, "upload.failed", "upload_job", job.id, None,
              {"attempts": job.attempts_count, "error_code": outcome.error_code})
    track(
        "upload.result", job.facility_id, "doctor", visit.id,
        status=job.status, attempts=job.attempts_count, error_code=outcome.error_code,
    )
