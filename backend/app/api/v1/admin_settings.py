"""إعدادات الترميز والربط واللوحات وسجل التدقيق وقائمة الرفع الفاشل — DOC-05 §٣ (FR-300/400)."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError

from ...audit import audit
from ...config import get_settings
from ...deps import AdminAuth, Auth, DB, pagination
from ...envelope import ok, paginated
from ...errors import MedifyError
from ...models import (
    AuditLog,
    Clinic,
    CodingSystemConfig,
    EditEvent,
    GuidanceItem,
    IntegrationConfig,
    Summary,
    UploadJob,
    User,
    Visit,
)
from ...services.uploader import process_upload_job

router = APIRouter()


# ===== أنظمة الترميز (FR-301) =====

@router.get("/settings/coding-systems")
def get_coding_systems(ctx: Auth, db: DB):
    """الأدمن: كامل الإعداد · الدكتور: الأنظمة النشطة فقط (DOC-06 §٢)."""
    rows = db.execute(
        select(CodingSystemConfig).where(CodingSystemConfig.facility_id == ctx.facility_id)
    ).scalars().all()
    if ctx.role == "doctor":
        return ok([{"system": r.system, "version": r.version} for r in rows if r.is_active])
    return ok([
        {"id": str(r.id), "system": r.system, "version": r.version, "is_active": r.is_active}
        for r in rows
    ])


class CodingSystemPatchIn(BaseModel):
    systems: dict[str, bool]  # {"ACHI": true, ...}


@router.patch("/settings/coding-systems")
def patch_coding_systems(body: CodingSystemPatchIn, ctx: AdminAuth, db: DB):
    """ICD10AM لا يُعطَّل — قيد CHECK في القاعدة هو الحكم (قرار مالك 2026-07-14)."""
    rows = {
        r.system: r
        for r in db.execute(
            select(CodingSystemConfig).where(CodingSystemConfig.facility_id == ctx.facility_id)
        ).scalars()
    }
    for system, active in body.systems.items():
        if system not in rows:
            raise MedifyError("MDF-4041", details={"system": system})
        rows[system].is_active = active
    try:
        db.flush()
    except (IntegrityError, DBAPIError) as exc:
        db.rollback()
        if "ck_icd10am_always_active" in str(exc.orig or exc):
            raise MedifyError("MDF-4031", details={"reason": "ICD10AM_cannot_be_disabled"}) from exc
        raise
    audit(db, ctx.facility_id, "coding_systems.updated", "coding_system_configs", None, ctx.user_id, body.systems)
    return ok({"updated": True})


# ===== الربط مع نظام المستشفى (FR-302) =====

@router.get("/settings/integration")
def get_integration(ctx: AdminAuth, db: DB):
    config = db.execute(
        select(IntegrationConfig).where(IntegrationConfig.facility_id == ctx.facility_id)
    ).scalar_one_or_none()
    if config is None:
        raise MedifyError("MDF-4041")
    return ok({
        "endpoint_url": config.endpoint_url,
        "mode": config.mode,
        "has_secret": bool(config.auth_secret_encrypted),
        "last_test_at": config.last_test_at.isoformat() if config.last_test_at else None,
        "last_test_ok": config.last_test_ok,
    })


class IntegrationPatchIn(BaseModel):
    endpoint_url: str | None = None
    auth_secret: str | None = None
    mode: str | None = None  # test | live


@router.patch("/settings/integration")
def patch_integration(body: IntegrationPatchIn, ctx: AdminAuth, db: DB):
    config = db.execute(
        select(IntegrationConfig).where(IntegrationConfig.facility_id == ctx.facility_id)
    ).scalar_one()
    if body.endpoint_url is not None:
        config.endpoint_url = body.endpoint_url
    if body.auth_secret is not None:
        config.auth_secret_encrypted = body.auth_secret  # يُشفَّر عمودياً (EncryptedText)
    if body.mode is not None:
        if body.mode not in ("test", "live"):
            raise MedifyError("MDF-4041", details={"mode": body.mode})
        config.mode = body.mode
    audit(db, ctx.facility_id, "integration.updated", "integration_configs", config.id, ctx.user_id,
          {"mode": config.mode})
    return ok({"updated": True})


@router.post("/settings/integration/test")
def test_integration(ctx: AdminAuth, db: DB):
    """اختبار الاتصال — يحدّث last_test_* (FR-302)."""
    config = db.execute(
        select(IntegrationConfig).where(IntegrationConfig.facility_id == ctx.facility_id)
    ).scalar_one()
    s = get_settings()
    ok_result = True
    if s.integration_engine == "mock":
        ok_result = "fail" not in (config.endpoint_url or "")
    else:
        import httpx
        try:
            response = httpx.get(config.endpoint_url or "", timeout=10)
            ok_result = response.status_code < 500
        except Exception:
            ok_result = False
    config.last_test_at = dt.datetime.now(dt.timezone.utc)
    config.last_test_ok = ok_result
    audit(db, ctx.facility_id, "integration.tested", "integration_configs", config.id, ctx.user_id, {"ok": ok_result})
    if not ok_result:
        from ...notify import notify_admins
        notify_admins(db, ctx.facility_id, "ad.integration_down", {"mdf": "MDF-5052"})
    return ok({"ok": ok_result, "tested_at": config.last_test_at.isoformat()})


# ===== اللوحات (FR-401/402) — تجميعات فقط، لا محتوى سريرياً =====

@router.get("/dashboards/usage")
def usage_dashboard(ctx: AdminAuth, db: DB):
    facility = ctx.facility_id
    by_doctor = db.execute(
        select(User.full_name, func.count(Visit.id))
        .join(Visit, Visit.doctor_id == User.id)
        .where(Visit.facility_id == facility)
        .group_by(User.full_name)
    ).all()
    by_clinic = db.execute(
        select(Clinic.name, func.count(Visit.id))
        .join(Visit, Visit.clinic_id == Clinic.id)
        .where(Visit.facility_id == facility)
        .group_by(Clinic.name)
    ).all()
    by_state = db.execute(
        select(Visit.state, func.count(Visit.id)).where(Visit.facility_id == facility).group_by(Visit.state)
    ).all()
    total = db.execute(select(func.count(Visit.id)).where(Visit.facility_id == facility)).scalar_one()
    return ok({
        "total_visits": total,
        "by_doctor": [{"doctor": name, "visits": count} for name, count in by_doctor],
        "by_clinic": [{"clinic": name, "visits": count} for name, count in by_clinic],
        "by_state": {state: count for state, count in by_state},
    })


@router.get("/dashboards/quality")
def quality_dashboard(ctx: AdminAuth, db: DB):
    facility = ctx.facility_id
    guidance_stats = db.execute(
        select(GuidanceItem.status, func.count(GuidanceItem.id))
        .where(GuidanceItem.facility_id == facility)
        .group_by(GuidanceItem.status)
    ).all()
    edits_by_channel = db.execute(
        select(EditEvent.channel, func.count(EditEvent.id))
        .where(EditEvent.facility_id == facility)
        .group_by(EditEvent.channel)
    ).all()
    summaries_total = db.execute(
        select(func.count(Summary.id)).where(Summary.facility_id == facility)
    ).scalar_one()
    edited_visits = db.execute(
        select(func.count(func.distinct(EditEvent.visit_id))).where(EditEvent.facility_id == facility)
    ).scalar_one()
    guidance = {status: count for status, count in guidance_stats}
    resolved = sum(count for status, count in guidance.items() if status != "pending")
    accepted = guidance.get("accepted", 0) + guidance.get("modified", 0)
    return ok({
        "summaries_total": summaries_total,
        "approved_without_edit_pct": round(100 * (1 - edited_visits / summaries_total), 1) if summaries_total else None,
        "guidance_by_status": guidance,
        "guidance_accept_rate_pct": round(100 * accepted / resolved, 1) if resolved else None,
        "edits_by_channel": {channel: count for channel, count in edits_by_channel},
    })


# ===== سجل التدقيق (FR-303) =====

@router.get("/audit-logs")
def audit_logs(ctx: AdminAuth, db: DB, page: int = 1, per_page: int = 25, action: str | None = None):
    page, per_page = pagination(page, per_page)
    base = select(AuditLog).where(AuditLog.facility_id == ctx.facility_id)
    if action:
        base = base.where(AuditLog.action.like(f"{action}%"))
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(base.order_by(AuditLog.at.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    actors = {
        u.id: u.full_name
        for u in db.execute(select(User).where(User.id.in_(actor_ids))).scalars()
    } if actor_ids else {}
    return paginated([
        {
            "id": str(r.id),
            "at": r.at.isoformat(),
            "actor": actors.get(r.actor_user_id, "النظام"),
            "action": r.action,
            "entity": r.entity,
            "entity_id": r.entity_id,
            "meta": r.meta_json,
        }
        for r in rows
    ], total, page, per_page)


# ===== قائمة الرفع الفاشل (W-209/FR-403) — بيانات وصفية فقط =====

@router.get("/uploads/failed")
def failed_uploads(ctx: AdminAuth, db: DB, page: int = 1, per_page: int = 25):
    page, per_page = pagination(page, per_page)
    base = (
        select(UploadJob, Visit, User.full_name)
        .join(Visit, Visit.id == UploadJob.visit_id)
        .join(User, User.id == Visit.doctor_id)
        .where(UploadJob.facility_id == ctx.facility_id, UploadJob.status == "failed")
    )
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(base.order_by(UploadJob.updated_at.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    out = []
    for job, visit, doctor_name in rows:
        from ...models import UploadAttempt
        last_attempt = db.execute(
            select(UploadAttempt).where(UploadAttempt.job_id == job.id).order_by(UploadAttempt.started_at.desc()).limit(1)
        ).scalar_one_or_none()
        out.append({
            "job_id": str(job.id),
            "visit_id": str(visit.id),
            "doctor": doctor_name,
            "attempts_count": job.attempts_count,
            "error_code": last_attempt.error_code if last_attempt else None,
            "failed_at": job.updated_at.isoformat(),
        })
    return paginated(out, total, page, per_page)


class RetryUploadsIn(BaseModel):
    job_ids: list[uuid.UUID]


@router.post("/uploads/retry")
def retry_uploads(body: RetryUploadsIn, ctx: AdminAuth, db: DB):
    """إعادة محاولة جماعية/انتقائية — تُسجَّل في audit_logs (DOC-05)."""
    results = []
    for job_id in body.job_ids:
        job = db.execute(select(UploadJob).where(UploadJob.id == job_id)).scalar_one_or_none()
        if job is None:
            results.append({"job_id": str(job_id), "ok": False, "reason": "not_found"})
            continue
        process_upload_job(db, job.id, manual=True)
        db.flush()
        refreshed = db.execute(select(UploadJob).where(UploadJob.id == job_id)).scalar_one()
        results.append({"job_id": str(job_id), "ok": refreshed.status == "confirmed", "status": refreshed.status})
    audit(db, ctx.facility_id, "uploads.bulk_retry", "upload_jobs", None, ctx.user_id,
          {"count": len(body.job_ids)})
    return ok({"results": results})
