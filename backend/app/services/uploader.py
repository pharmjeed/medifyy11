"""عامل الرفع لنظام المستشفى — INTEGRATION_ENGINE=mock|http + إعادة محاولة آلية (FR-805)."""
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
from ..models import IntegrationConfig, UploadAttempt, UploadJob, Visit
from ..notify import notify, notify_admins

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

    max_attempts = 1 if manual else s.upload_max_auto_attempts
    outcome = UploadOutcome(False, "MDF-5052")
    for _ in range(max_attempts):
        job.status = "sent"
        job.attempts_count += 1
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
        visit.state = "uploaded"
        db.flush()
        notify(db, job.facility_id, visit.doctor_id, "dr.upload_success", {"visit_id": str(visit.id)})
        audit(db, job.facility_id, "upload.confirmed", "upload_job", job.id, None, {"attempts": job.attempts_count})
    else:
        job.status = "failed"
        if visit.state == "approved":
            visit.state = "upload_failed"
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
