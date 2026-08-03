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
    RetentionPolicy,
    Summary,
    SummarySection,
    UploadJob,
    User,
    Visit,
)
from ...services.metrics import metrics_summary
from ...services.retention import DEFAULTS as RETENTION_DEFAULTS
from ...services.retention import effective_policies, retention_status
from ...services.uploader import process_upload_job

router = APIRouter()


# ===== لوحة المقاييس المجمّعة (م15) =====

@router.get("/admin/metrics/summary")
def admin_metrics_summary(ctx: AdminAuth, db: DB, date_from: str | None = None,
                          date_to: str | None = None, group_by: str = "facility"):
    """المقاييس من التجميع الليلي حصراً — أرقام فقط بلا أي محتوى سريري (RBAC أدمن)."""
    today = dt.date.today()
    try:
        start = dt.date.fromisoformat(date_from) if date_from else today - dt.timedelta(days=30)
        end = dt.date.fromisoformat(date_to) if date_to else today
    except ValueError:
        raise MedifyError("MDF-4041", details={"from": date_from, "to": date_to})
    return ok(metrics_summary(db, ctx.facility_id, start, end, group_by))


# ===== سياسة الاحتفاظ الموحّدة (م8) =====

@router.get("/settings/retention")
def get_retention_policies(ctx: AdminAuth, db: DB):
    """السياسات الفعلية (الافتراضات + تجاوزات المنشأة) — docs/retention-policy.md المرجع."""
    return ok({"policies": effective_policies(db, ctx.facility_id),
               "defaults": RETENTION_DEFAULTS, "grace_days": 7})


class RetentionPatchIn(BaseModel):
    artifact_type: str
    retention_days: int | None = None  # NULL = بلا حذف


@router.patch("/settings/retention")
def patch_retention_policy(body: RetentionPatchIn, ctx: AdminAuth, db: DB):
    if body.artifact_type not in RETENTION_DEFAULTS:
        raise MedifyError("MDF-4041", details={"artifact_type": body.artifact_type,
                                               "allowed": sorted(RETENTION_DEFAULTS)})
    if body.retention_days is not None and body.retention_days < 1:
        raise MedifyError("MDF-4225", details={"retention_days": body.retention_days})
    row = db.execute(
        select(RetentionPolicy).where(
            RetentionPolicy.facility_id == ctx.facility_id,
            RetentionPolicy.artifact_type == body.artifact_type,
        )
    ).scalar_one_or_none()
    if row is None:
        row = RetentionPolicy(facility_id=ctx.facility_id, artifact_type=body.artifact_type)
        db.add(row)
    row.retention_days = body.retention_days
    row.updated_by = ctx.user_id
    db.flush()
    audit(db, ctx.facility_id, "retention.policy_updated", "retention_policy", row.id, ctx.user_id,
          {"artifact_type": body.artifact_type, "retention_days": body.retention_days})
    return ok({"policies": effective_policies(db, ctx.facility_id)})


@router.get("/admin/retention-status")
def admin_retention_status(ctx: AdminAuth, db: DB):
    """ما سيُحذف خلال 7 أيام + الموسوم بانتظار الحذف الصلب — أعداد فقط، بلا محتوى."""
    return ok(retention_status(db, ctx.facility_id))


class LegalHoldIn(BaseModel):
    enabled: bool


@router.post("/visits/{visit_id}/legal-hold")
def set_legal_hold(visit_id: uuid.UUID, body: LegalHoldIn, ctx: AdminAuth, db: DB):
    """تجميد/فك تجميد الحذف الاحتفاظي لأثار زيارة (تحقيق/نزاع) — أدمن حصراً + Audit."""
    visit = db.execute(select(Visit).where(Visit.id == visit_id)).scalar_one_or_none()
    if visit is None:
        raise MedifyError("MDF-4041")
    visit.legal_hold = body.enabled
    db.flush()
    audit(db, ctx.facility_id, "visit.legal_hold_set", "visit", visit.id, ctx.user_id,
          {"enabled": body.enabled})
    return ok({"visit_id": str(visit.id), "legal_hold": visit.legal_hold})


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
    # المبطلة تُستثنى من عدادات الإنتاجية (قرار مالك 2026-08-03) — وتبقى ظاهرة في
    # توزيع الحالات by_state كي لا تختفي واقعة الإبطال عن الأدمن (Void ≠ Delete)
    by_doctor = db.execute(
        select(User.full_name, func.count(Visit.id))
        .join(Visit, Visit.doctor_id == User.id)
        .where(Visit.facility_id == facility, Visit.state != "voided")
        .group_by(User.full_name)
    ).all()
    by_clinic = db.execute(
        select(Clinic.name, func.count(Visit.id))
        .join(Visit, Visit.clinic_id == Clinic.id)
        .where(Visit.facility_id == facility, Visit.state != "voided")
        .group_by(Clinic.name)
    ).all()
    by_state = db.execute(
        select(Visit.state, func.count(Visit.id)).where(Visit.facility_id == facility).group_by(Visit.state)
    ).all()
    total = db.execute(
        select(func.count(Visit.id)).where(Visit.facility_id == facility, Visit.state != "voided")
    ).scalar_one()
    return ok({
        "total_visits": total,
        "by_doctor": [{"doctor": name, "visits": count} for name, count in by_doctor],
        "by_clinic": [{"clinic": name, "visits": count} for name, count in by_clinic],
        "by_state": {state: count for state, count in by_state},
    })


@router.get("/dashboards/quality")
def quality_dashboard(ctx: AdminAuth, db: DB):
    facility = ctx.facility_id
    # مؤشرات الجودة تقيس عمل الدكاترة الفعلي — زيارة مبطلة (مريض خطأ/مكررة/تجريبية)
    # تلوّثها، فتُستثنى بكاملها: ملخصاتها وإرشاداتها وتعديلاتها (قرار مالك 2026-08-03)
    voided_visits = select(Visit.id).where(Visit.facility_id == facility, Visit.state == "voided")
    guidance_stats = db.execute(
        select(GuidanceItem.status, func.count(GuidanceItem.id))
        .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
        .join(Summary, Summary.id == SummarySection.summary_id)
        .where(GuidanceItem.facility_id == facility, Summary.visit_id.not_in(voided_visits))
        .group_by(GuidanceItem.status)
    ).all()
    edits_by_channel = db.execute(
        select(EditEvent.channel, func.count(EditEvent.id))
        .where(EditEvent.facility_id == facility, EditEvent.visit_id.not_in(voided_visits))
        .group_by(EditEvent.channel)
    ).all()
    summaries_total = db.execute(
        select(func.count(Summary.id)).where(
            Summary.facility_id == facility, Summary.visit_id.not_in(voided_visits)
        )
    ).scalar_one()
    edited_visits = db.execute(
        select(func.count(func.distinct(EditEvent.visit_id))).where(
            EditEvent.facility_id == facility, EditEvent.visit_id.not_in(voided_visits)
        )
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
    # id (UUID v7) كاسر تعادل — أسطر المعاملة الواحدة تتشارك at نفسه (server now())
    rows = db.execute(
        base.order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()
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


# ===== البرومبتات (FR-500+) =====

@router.get("/templates/prompts")
def admin_list_template_prompts(ctx: AdminAuth, db: DB):
    """قائمة بالبرومبتات الافتراضية والمخصصة."""
    from ...models import PlatformDefaultPrompt, Template

    # الحصول على البرومبتات الافتراضية النشطة
    default_prompts = db.execute(
        select(PlatformDefaultPrompt).where(PlatformDefaultPrompt.is_active == True)
    ).scalars().all()

    defaults_map = {p.template_type: p.prompt_content for p in default_prompts}

    # الحصول على جميع قوالب المنشأة
    templates = db.execute(
        select(Template).where(
            Template.facility_id == ctx.facility_id,
            Template.archived_at.is_(None)
        )
    ).scalars().all()

    result = []
    for tpl in templates:
        prompt = tpl.prompt_content or defaults_map.get(tpl.prompt_template_type)
        result.append({
            "template_id": str(tpl.id),
            "template_name": tpl.name,
            "prompt_source": tpl.prompt_source,
            "prompt_template_type": tpl.prompt_template_type,
            "has_custom_prompt": tpl.prompt_source == "custom" and tpl.prompt_content is not None,
            "prompt_preview": (prompt[:100] + "...") if prompt else None,
        })

    return ok(result)


class AdminUpdatePromptIn(BaseModel):
    """تحديث برومبت قالب معين."""
    prompt_content: str = None  # None = استخدام الديفولت
    prompt_source: str = "custom"  # custom أو default


@router.patch("/templates/{template_id}/prompt")
def admin_update_template_prompt(template_id: uuid.UUID, body: AdminUpdatePromptIn, ctx: AdminAuth, db: DB):
    """تحديث/حذف برومبت مخصص للقالب."""
    from ...models import Template

    tpl = db.execute(
        select(Template).where(
            Template.id == template_id,
            Template.facility_id == ctx.facility_id
        )
    ).scalar_one_or_none()

    if tpl is None:
        raise MedifyError("MDF-4041", details={"template_id": str(template_id)})

    # إذا كان body.prompt_content None، يتم حذف البرومبت المخصص والعودة للديفولت
    if body.prompt_content is None:
        tpl.prompt_content = None
        tpl.prompt_source = "default"
    else:
        tpl.prompt_content = body.prompt_content
        tpl.prompt_source = body.prompt_source

    tpl.updated_at = dt.datetime.now(dt.timezone.utc)
    audit(db, ctx.facility_id, "template.prompt_updated", "templates", template_id, ctx.user_id,
          {"prompt_source": tpl.prompt_source})

    return ok({
        "template_id": str(tpl.id),
        "prompt_source": tpl.prompt_source,
        "message": "Prompt updated successfully",
    })
