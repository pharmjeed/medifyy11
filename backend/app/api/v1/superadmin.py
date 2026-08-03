"""طبقة السوبر أدمن /sa — كونسول مالك المنصة (DOC-20 v1.1 معتمدة 2026-07-16).

المبادئ الحاكمة:
- محرك النظام (يتجاوز RLS) — كل استعلام يقيَّد بمعرّفات صريحة.
- لا محتوى سريرياً أبداً — عدادات وتجميعات فقط (نفس قيد أدمن المنشأة DOC-06).
- حارس مزدوج: scope=platform + درجة الحساب (owner/ops/finance/support/read_only).
- كل فعل يُدوَّن مزدوجاً: platform_audit_logs (الموحّد) + audit_logs المنشأة المعنية.
- إعادة مصادقة TOTP (X-SA-Reauth) للإجراءات الحسّاسة عند تفعيل 2FA.
"""
from __future__ import annotations

import datetime as dt
import logging
import secrets
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, Request, Response, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...audit import audit
from ...config import get_settings
from ...db import get_system_db
from ...deps import SuperAdminContext, SuperAuth, pagination, require_cap, require_reauth
from ...envelope import ok, paginated
from ...errors import MedifyError
from ...features import CORE_KEYS, FEATURE_BY_KEY, FEATURE_GROUPS, catalog_out
from ...models import (
    Clinic,
    CodingSystemConfig,
    Facility,
    IntegrationConfig,
    Invoice,
    Plan,
    PlatformAdmin,
    PlatformAuditLog,
    PlatformDefaultPrompt,
    SeatEvent,
    Subscription,
    User,
)
from ...security import (
    create_sa_access_token,
    create_sa_refresh_token,
    decode_token,
    hash_password,
    lockout,
    verify_password,
)
from ...services.billing import issue_invoice, plan_seat_price, seats_used
from ...services.default_templates import seed_default_templates
from ...services.features import plan_features
from ...totp import (
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    otpauth_uri,
    verify_totp,
)

router = APIRouter(prefix="/sa")
logger = logging.getLogger("medify.sa")

SystemDB = Annotated[Session, Depends(get_system_db)]

SA_REFRESH_COOKIE = "medify_sa_refresh"
SA_LOCKOUT_KEY = "__platform__"  # مفتاح قفل المحاولات — منفصل عن مفاتيح المنشآت


def sa_audit(
    db: Session,
    ctx: SuperAdminContext,
    action: str,
    entity: str,
    entity_id: uuid.UUID | str | None = None,
    facility_id: uuid.UUID | None = None,
    meta: dict | None = None,
) -> None:
    """التدوين المزدوج (DOC-20 §٤ W-SA-09): السجل الموحّد دائماً + سجل المنشأة إن كان الفعل عليها."""
    db.add(PlatformAuditLog(
        actor_admin_id=ctx.admin_id,
        actor_username=ctx.username,
        actor_role=ctx.role,
        action=action,
        facility_id=facility_id,
        entity=entity,
        entity_id=str(entity_id) if entity_id else None,
        ip=ctx.ip,
        meta_json=meta,
        at=dt.datetime.now(dt.timezone.utc),
    ))
    if facility_id is not None:
        audit(db, facility_id, action, entity, entity_id, None, {"sa": ctx.username, **(meta or {})})


# ════════════════ المصادقة ════════════════

class SaLoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    totp_code: str | None = None  # إلزامي إن كان 2FA مفعّلاً — يقبل رمز استرداد أيضاً


def _set_sa_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        SA_REFRESH_COOKIE,
        token,
        httponly=True,
        secure=s.environment != "dev",
        samesite="lax",
        max_age=s.refresh_token_days * 86400,
        path="/api/v1/sa/auth",
    )


def _admin_out(admin: PlatformAdmin) -> dict:
    return {
        "id": str(admin.id),
        "username": admin.username,
        "full_name": admin.full_name,
        "email": admin.email,
        "role": admin.role,
        "totp_enabled": admin.totp_enabled,
        "is_active": admin.is_active,
        "last_login_at": admin.last_login_at.isoformat() if admin.last_login_at else None,
        "created_at": admin.created_at.isoformat(),
    }


def _consume_recovery_code(admin: PlatformAdmin, code: str) -> bool:
    """رمز استرداد يُصرف لمرة واحدة — القائمة تحمل هاشات فقط."""
    hashes: list[str] = list(admin.recovery_codes or [])
    hashed = hash_recovery_code(code)
    if hashed not in hashes:
        return False
    hashes.remove(hashed)
    admin.recovery_codes = hashes
    return True


@router.post("/auth/login")
def sa_login(body: SaLoginIn, request: Request, response: Response, db: SystemDB):
    if lockout.is_locked(SA_LOCKOUT_KEY, body.username):
        raise MedifyError("MDF-4011", details={"locked": True})
    admin = db.execute(
        select(PlatformAdmin).where(PlatformAdmin.username == body.username)
    ).scalar_one_or_none()
    if admin is None or not verify_password(admin.password_hash, body.password):
        lockout.record_failure(SA_LOCKOUT_KEY, body.username)
        raise MedifyError("MDF-4011")
    if not admin.is_active:
        raise MedifyError("MDF-4013")

    # المصادقة الثنائية (DOC-20 §١.٣) — TOTP أو رمز استرداد لمرة واحدة
    if admin.totp_enabled:
        code = (body.totp_code or "").strip()
        if not code:
            raise MedifyError("MDF-4015", details={"totp_required": True})
        secret = admin.totp_secret_encrypted or ""
        if not verify_totp(secret, code) and not _consume_recovery_code(admin, code):
            lockout.record_failure(SA_LOCKOUT_KEY, body.username)
            raise MedifyError("MDF-4015", details={"totp_required": True})

    lockout.reset(SA_LOCKOUT_KEY, body.username)
    admin.last_login_at = dt.datetime.now(dt.timezone.utc)
    _set_sa_refresh_cookie(response, create_sa_refresh_token(admin.id))
    logger.info("sa.login username=%s role=%s", admin.username, admin.role)
    return ok({"access_token": create_sa_access_token(admin.id), "admin": _admin_out(admin)})


@router.post("/auth/refresh")
def sa_refresh(request: Request, response: Response, db: SystemDB):
    token = request.cookies.get(SA_REFRESH_COOKIE)
    if not token:
        raise MedifyError("MDF-4012")
    payload = decode_token(token, "refresh")
    if payload.get("role") != "super_admin" or payload.get("scope") != "platform":
        raise MedifyError("MDF-4012")
    admin = db.execute(
        select(PlatformAdmin).where(PlatformAdmin.id == uuid.UUID(payload["sub"]))
    ).scalar_one_or_none()
    if admin is None or not admin.is_active:
        raise MedifyError("MDF-4012")
    _set_sa_refresh_cookie(response, create_sa_refresh_token(admin.id))
    return ok({"access_token": create_sa_access_token(admin.id)})


@router.post("/auth/logout")
def sa_logout(response: Response):
    response.delete_cookie(SA_REFRESH_COOKIE, path="/api/v1/sa/auth")
    return ok({"logged_out": True})


@router.get("/me")
def sa_me(ctx: SuperAuth):
    return ok(_admin_out(ctx.admin))


class SaChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


@router.patch("/me/password")
def sa_change_password(body: SaChangePasswordIn, ctx: SuperAuth, db: SystemDB):
    admin = db.execute(select(PlatformAdmin).where(PlatformAdmin.id == ctx.admin_id)).scalar_one()
    if not verify_password(admin.password_hash, body.current_password):
        raise MedifyError("MDF-4011")
    admin.password_hash = hash_password(body.new_password)
    sa_audit(db, ctx, "sa.password_changed", "platform_admin", admin.id)
    return ok({"changed": True})


# ════════════════ المصادقة الثنائية 2FA (W-SA-12) ════════════════

@router.post("/me/2fa/setup")
def sa_2fa_setup(ctx: SuperAuth, db: SystemDB):
    """يولّد سراً معلّقاً (لا يفعّل) — التفعيل بعد التحقق من أول رمز."""
    admin = db.execute(select(PlatformAdmin).where(PlatformAdmin.id == ctx.admin_id)).scalar_one()
    if admin.totp_enabled:
        raise MedifyError("MDF-4015", details={"reason": "already_enabled"})
    secret = generate_secret()
    admin.totp_secret_encrypted = secret  # يُشفَّر عمودياً (EncryptedText)
    return ok({"secret": secret, "otpauth_uri": otpauth_uri(secret, admin.username)})


class Sa2faCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


@router.post("/me/2fa/enable")
def sa_2fa_enable(body: Sa2faCodeIn, ctx: SuperAuth, db: SystemDB):
    """يتحقق من أول رمز ويفعّل — يعيد رموز الاسترداد مرة واحدة فقط."""
    admin = db.execute(select(PlatformAdmin).where(PlatformAdmin.id == ctx.admin_id)).scalar_one()
    if admin.totp_enabled:
        raise MedifyError("MDF-4015", details={"reason": "already_enabled"})
    secret = admin.totp_secret_encrypted
    if not secret or not verify_totp(secret, body.code):
        raise MedifyError("MDF-4015")
    raw_codes = generate_recovery_codes()
    admin.recovery_codes = [hash_recovery_code(c) for c in raw_codes]
    admin.totp_enabled = True
    sa_audit(db, ctx, "sa.2fa_enabled", "platform_admin", admin.id)
    return ok({"enabled": True, "recovery_codes": raw_codes})


@router.post("/me/2fa/disable")
def sa_2fa_disable(body: Sa2faCodeIn, ctx: SuperAuth, db: SystemDB):
    """تعطيل 2FA يتطلب رمزاً حياً — على الإنتاج سيُطالَب بالإعداد من جديد عند التالي."""
    admin = db.execute(select(PlatformAdmin).where(PlatformAdmin.id == ctx.admin_id)).scalar_one()
    if not admin.totp_enabled:
        return ok({"enabled": False})
    secret = admin.totp_secret_encrypted or ""
    if not verify_totp(secret, body.code) and not _consume_recovery_code(admin, body.code):
        raise MedifyError("MDF-4015")
    admin.totp_enabled = False
    admin.totp_secret_encrypted = None
    admin.recovery_codes = None
    sa_audit(db, ctx, "sa.2fa_disabled", "platform_admin", admin.id)
    return ok({"enabled": False})


# ════════════════ إدارة حسابات السوبر أدمن (W-SA-11 — owner حصراً) ════════════════

PLATFORM_ROLES = ("owner", "ops", "finance", "support", "read_only")


def _active_owners_count(db: Session, excluding: uuid.UUID | None = None) -> int:
    query = select(func.count(PlatformAdmin.id)).where(
        PlatformAdmin.role == "owner", PlatformAdmin.is_active == True  # noqa: E712
    )
    if excluding is not None:
        query = query.where(PlatformAdmin.id != excluding)
    return db.execute(query).scalar_one()


@router.get("/admins")
def sa_list_admins(ctx: SuperAuth, db: SystemDB):
    require_cap(ctx, "admins.manage")
    admins = db.execute(select(PlatformAdmin).order_by(PlatformAdmin.created_at)).scalars().all()
    return ok([_admin_out(a) for a in admins])


class SaAdminCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9][a-z0-9\.\-_]*$")
    full_name: str = Field(min_length=2)
    email: EmailStr | None = None
    password: str = Field(min_length=10)
    role: Literal["owner", "ops", "finance", "support", "read_only"]


@router.post("/admins", status_code=201)
def sa_create_admin(body: SaAdminCreateIn, ctx: SuperAuth, request: Request, db: SystemDB):
    require_cap(ctx, "admins.manage")
    require_reauth(ctx, request)
    duplicate = db.execute(
        select(PlatformAdmin).where(PlatformAdmin.username == body.username)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise MedifyError("MDF-4041", details={"reason": "username_taken"})
    admin = PlatformAdmin(
        username=body.username,
        full_name=body.full_name,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
        invited_by=ctx.admin_id,
    )
    db.add(admin)
    db.flush()
    sa_audit(db, ctx, "sa.admin_created", "platform_admin", admin.id,
             meta={"username": body.username, "role": body.role})
    return ok(_admin_out(admin))


class SaAdminPatchIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2)
    email: EmailStr | None = None
    role: Literal["owner", "ops", "finance", "support", "read_only"] | None = None
    is_active: bool | None = None


@router.patch("/admins/{admin_id}")
def sa_patch_admin(admin_id: uuid.UUID, body: SaAdminPatchIn, ctx: SuperAuth, request: Request, db: SystemDB):
    require_cap(ctx, "admins.manage")
    require_reauth(ctx, request)
    admin = db.execute(select(PlatformAdmin).where(PlatformAdmin.id == admin_id)).scalar_one_or_none()
    if admin is None:
        raise MedifyError("MDF-4041")

    # حماية آخر مالك فعّال (MDF-4229 — DOC-20 §٤ W-SA-11)
    losing_owner = admin.role == "owner" and admin.is_active and (
        (body.role is not None and body.role != "owner") or body.is_active is False
    )
    if losing_owner and _active_owners_count(db, excluding=admin.id) == 0:
        raise MedifyError("MDF-4229")

    changes: dict[str, object] = {}
    if body.full_name is not None:
        admin.full_name = body.full_name
    if body.email is not None:
        admin.email = body.email
    if body.role is not None and body.role != admin.role:
        changes["role"] = {"from": admin.role, "to": body.role}
        admin.role = body.role
    if body.is_active is not None and body.is_active != admin.is_active:
        changes["is_active"] = body.is_active
        admin.is_active = body.is_active
        admin.disabled_at = None if body.is_active else dt.datetime.now(dt.timezone.utc)
    if changes:
        sa_audit(db, ctx, "sa.admin_updated", "platform_admin", admin.id, meta=changes)
    return ok(_admin_out(admin))


@router.post("/admins/{admin_id}/reset-password")
def sa_reset_admin_password(admin_id: uuid.UUID, ctx: SuperAuth, request: Request, db: SystemDB):
    require_cap(ctx, "admins.manage")
    require_reauth(ctx, request)
    admin = db.execute(select(PlatformAdmin).where(PlatformAdmin.id == admin_id)).scalar_one_or_none()
    if admin is None:
        raise MedifyError("MDF-4041")
    temp_password = "Md-" + secrets.token_urlsafe(10)
    admin.password_hash = hash_password(temp_password)
    sa_audit(db, ctx, "sa.admin_password_reset", "platform_admin", admin.id)
    return ok({"temporary_password": temp_password})


# ════════════════ سجل المنصة الموحّد (W-SA-09) ════════════════

@router.get("/audit")
def sa_platform_audit(
    ctx: SuperAuth, db: SystemDB,
    facility_id: str = "", action: str = "", actor: str = "",
    page: int = 1, per_page: int = 50,
):
    page, per_page = pagination(page, per_page)
    base = select(PlatformAuditLog)
    if facility_id:
        try:
            base = base.where(PlatformAuditLog.facility_id == uuid.UUID(facility_id))
        except ValueError:
            raise MedifyError("MDF-4041", details={"reason": "bad_facility_id"})
    if action:
        base = base.where(PlatformAuditLog.action.ilike(f"%{action}%"))
    if actor:
        base = base.where(PlatformAuditLog.actor_username.ilike(f"%{actor}%"))
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(
        base.order_by(PlatformAuditLog.at.desc()).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()
    facility_names = dict(db.execute(
        select(Facility.id, Facility.name).where(
            Facility.id.in_({r.facility_id for r in rows if r.facility_id})
        )
    ).all()) if rows else {}
    return paginated([
        {
            "id": str(r.id),
            "at": r.at.isoformat(),
            "actor": r.actor_username,
            "actor_role": r.actor_role,
            "action": r.action,
            "facility_id": str(r.facility_id) if r.facility_id else None,
            "facility_name": facility_names.get(r.facility_id),
            "entity": r.entity,
            "entity_id": r.entity_id,
            "ip": r.ip,
            "meta": r.meta_json,
        }
        for r in rows
    ], total, page, per_page)


# ════════════════ نظرة المنصة ════════════════

@router.get("/overview")
def sa_overview(ctx: SuperAuth, db: SystemDB):
    """عدادات وتجميعات فقط — لا محتوى سريرياً (DOC-06 يسري على المنصة أيضاً)."""
    fac_by_status = dict(db.execute(select(Facility.status, func.count(Facility.id)).group_by(Facility.status)).all())
    doctors_active = db.execute(
        select(func.count(User.id)).where(User.role == "doctor", User.is_active == True)  # noqa: E712
    ).scalar_one()
    doctors_total = db.execute(select(func.count(User.id)).where(User.role == "doctor")).scalar_one()
    admins_total = db.execute(select(func.count(User.id)).where(User.role == "admin")).scalar_one()
    seats_sold = db.execute(select(func.coalesce(func.sum(Subscription.seats_total), 0))).scalar_one()

    inv_counts = dict(db.execute(select(Invoice.status, func.count(Invoice.id)).group_by(Invoice.status)).all())
    outstanding = db.execute(
        select(func.coalesce(func.sum(Invoice.amount_sar + Invoice.vat_sar), 0))
        .where(Invoice.status.in_(["due", "overdue"]))
    ).scalar_one()
    collected = db.execute(
        select(func.coalesce(func.sum(Invoice.amount_sar + Invoice.vat_sar), 0))
        .where(Invoice.status == "paid")
    ).scalar_one()
    month_start = dt.datetime.now(dt.timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    collected_month = db.execute(
        select(func.coalesce(func.sum(Invoice.amount_sar + Invoice.vat_sar), 0))
        .where(Invoice.status == "paid", Invoice.paid_at >= month_start)
    ).scalar_one()

    return ok({
        "facilities": {
            "total": sum(fac_by_status.values()),
            "active": fac_by_status.get("active", 0),
            "suspended": fac_by_status.get("suspended", 0),
            "archived": fac_by_status.get("archived", 0),
        },
        "users": {
            "doctors_active": doctors_active,
            "doctors_total": doctors_total,
            "admins_total": admins_total,
        },
        "seats_sold": int(seats_sold),
        "invoices": {
            "due": inv_counts.get("due", 0),
            "overdue": inv_counts.get("overdue", 0),
            "paid": inv_counts.get("paid", 0),
            "void": inv_counts.get("void", 0),
            "outstanding_sar": str(Decimal(outstanding).quantize(Decimal("0.01"))),
            "collected_sar": str(Decimal(collected).quantize(Decimal("0.01"))),
            "collected_this_month_sar": str(Decimal(collected_month).quantize(Decimal("0.01"))),
        },
    })


# ════════════════ المنشآت ════════════════

def _facility_row(db: Session, facility: Facility) -> dict:
    subscription = db.execute(
        select(Subscription).where(Subscription.facility_id == facility.id)
    ).scalar_one_or_none()
    used = seats_used(db, facility.id)
    admins = db.execute(
        select(func.count(User.id)).where(User.facility_id == facility.id, User.role == "admin")
    ).scalar_one()
    overdue = db.execute(
        select(func.count(Invoice.id)).where(Invoice.facility_id == facility.id, Invoice.status == "overdue")
    ).scalar_one()
    return {
        "id": str(facility.id),
        "name": facility.name,
        "commercial_reg": facility.commercial_reg,
        "status": facility.status,
        "created_at": facility.created_at.isoformat(),
        "plan": subscription.plan if subscription else None,
        "seats_total": subscription.seats_total if subscription else 0,
        "doctors_active": used,
        "admins_count": admins,
        "overdue_count": overdue,
    }


@router.get("/facilities")
def sa_list_facilities(
    ctx: SuperAuth, db: SystemDB,
    q: str = "", status: str = "", page: int = 1, per_page: int = 25,
):
    page, per_page = pagination(page, per_page)
    base = select(Facility)
    if q:
        base = base.where(Facility.name.ilike(f"%{q}%") | Facility.commercial_reg.ilike(f"%{q}%"))
    if status in ("active", "suspended", "archived"):
        base = base.where(Facility.status == status)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(
        base.order_by(Facility.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()
    return paginated([_facility_row(db, facility) for facility in rows], total, page, per_page)


class SaFacilityAdminIn(BaseModel):
    full_name: str = Field(min_length=2)
    username: str = Field(min_length=3)
    email: EmailStr  # إلزامي للأدمن — قناة الاستعادة (DOC-04)
    password: str = Field(min_length=8)


class SaFacilityCreateIn(BaseModel):
    name: str = Field(min_length=2)
    commercial_reg: str = Field(min_length=4)
    admin: SaFacilityAdminIn
    seats: int = Field(ge=1, le=500)   # عدد الدكاترة (§٠.١ تعديل ٢)
    plan: str = "monthly"              # دورة الفوترة — السعر من كتالوج المنصة
    issue_first_invoice: bool = False  # الإصدار من المنصة فعل صريح لا تلقائي


@router.post("/facilities", status_code=201)
def sa_create_facility(body: SaFacilityCreateIn, ctx: SuperAuth, db: SystemDB):
    """إنشاء منشأة من المنصة — نفس أثر التسجيل الذاتي (W-002) بفاعل منصّي (actor NULL).

    الفاتورة الأولى اختيارية خلافاً للتسجيل الذاتي: الإصدار من المنصة فعل صريح (§٠.١)،
    فتُترك مطفأة لحسابات العرض والتجريب.
    """
    require_cap(ctx, "facilities.write")
    if db.execute(
        select(Facility).where(Facility.commercial_reg == body.commercial_reg)
    ).scalar_one_or_none() is not None:
        raise MedifyError("MDF-4041", details={"reason": "commercial_reg_taken"})
    plan = db.execute(select(Plan).where(Plan.code == body.plan)).scalar_one_or_none()
    if plan is None or not plan.is_active:
        raise MedifyError("MDF-4041", details={"reason": "plan_not_found_or_inactive"})

    facility = Facility(name=body.name, commercial_reg=body.commercial_reg, status="active")
    db.add(facility)
    db.flush()
    admin = User(
        facility_id=facility.id,
        role="admin",
        full_name=body.admin.full_name,
        username=body.admin.username,
        email=body.admin.email,
        password_hash=hash_password(body.admin.password),
        is_active=True,
    )
    db.add(admin)
    subscription = Subscription(facility_id=facility.id, seats_total=body.seats, plan=plan.code)
    db.add(subscription)
    db.flush()
    # NULL = فعل المنصة (لا مستخدم منشأة وراءه)
    db.add(SeatEvent(subscription_id=subscription.id, delta=body.seats,
                     reason="expand", actor_user_id=None))
    # أنظمة الترميز الافتراضية — الحزمة السعودية (FR-301)
    for system in ("ICD10AM", "ACHI", "SBS", "SFDA"):
        db.add(CodingSystemConfig(facility_id=facility.id, system=system, version="2024", is_active=True))
    db.add(IntegrationConfig(facility_id=facility.id, mode="test"))
    # قوالب SOAP القياسية — بدونها لا يستطيع أي دكتور بدء زيارة (W-211)
    seed_default_templates(db, facility.id)
    invoice_number = issue_invoice(db, subscription, body.seats).number if body.issue_first_invoice else None
    sa_audit(db, ctx, "sa.facility_created", "facility", facility.id,
             facility_id=facility.id,
             meta={"name": facility.name, "seats": body.seats, "plan": plan.code,
                   "admin_username": admin.username, "invoiced": invoice_number is not None})
    return ok({
        "id": str(facility.id),
        "name": facility.name,
        "commercial_reg": facility.commercial_reg,
        "admin_username": admin.username,
        "seats_total": body.seats,
        "plan": plan.code,
        "invoice_number": invoice_number,
    })


def _get_facility(db: Session, facility_id: uuid.UUID) -> Facility:
    facility = db.execute(select(Facility).where(Facility.id == facility_id)).scalar_one_or_none()
    if facility is None:
        raise MedifyError("MDF-4041")
    return facility


def _user_out(user: User, clinics: dict[uuid.UUID, str]) -> dict:
    return {
        "id": str(user.id),
        "role": user.role,
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "specialty": user.specialty,
        "clinic_id": str(user.clinic_id) if user.clinic_id else None,
        "clinic_name": clinics.get(user.clinic_id) if user.clinic_id else None,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
    }


def _invoice_out(invoice: Invoice, facility_name: str | None = None) -> dict:
    out = {
        "id": str(invoice.id),
        "number": invoice.number,
        "facility_id": str(invoice.facility_id),
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "amount_sar": str(invoice.amount_sar),
        "vat_sar": str(invoice.vat_sar),
        "total_sar": str(invoice.amount_sar + invoice.vat_sar),
        "status": invoice.status,
        "issued_at": invoice.issued_at.isoformat(),
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "provider_ref": invoice.provider_ref,
    }
    if facility_name is not None:
        out["facility_name"] = facility_name
    return out


@router.get("/facilities/{facility_id}")
def sa_facility_detail(facility_id: uuid.UUID, ctx: SuperAuth, db: SystemDB):
    facility = _get_facility(db, facility_id)
    subscription = db.execute(
        select(Subscription).where(Subscription.facility_id == facility.id)
    ).scalar_one_or_none()
    used = seats_used(db, facility.id)
    clinics = {
        c.id: c.name
        for c in db.execute(select(Clinic).where(Clinic.facility_id == facility.id)).scalars()
    }
    users = db.execute(
        select(User).where(User.facility_id == facility.id).order_by(User.role, User.created_at)
    ).scalars().all()
    invoices = db.execute(
        select(Invoice).where(Invoice.facility_id == facility.id)
        .order_by(Invoice.issued_at.desc()).limit(50)
    ).scalars().all()
    seat_events: list[SeatEvent] = []
    plan_info = None
    if subscription is not None:
        seat_events = list(db.execute(
            select(SeatEvent).where(SeatEvent.subscription_id == subscription.id)
            .order_by(SeatEvent.created_at.desc()).limit(20)
        ).scalars())
        plan = db.execute(select(Plan).where(Plan.code == subscription.plan)).scalar_one_or_none()
        plan_info = _plan_out(db, plan) if plan else None
    return ok({
        "facility": {
            "id": str(facility.id),
            "name": facility.name,
            "commercial_reg": facility.commercial_reg,
            "status": facility.status,
            "created_at": facility.created_at.isoformat(),
        },
        "subscription": {
            "plan": subscription.plan,
            "seats_total": subscription.seats_total,
            "seats_used": used,
            "seats_available": subscription.seats_total - used,
            "plan_info": plan_info,
        } if subscription else None,
        "clinics": [
            {"id": str(cid), "name": name} for cid, name in clinics.items()
        ],
        "users": [_user_out(user, clinics) for user in users],
        "invoices": [_invoice_out(invoice) for invoice in invoices],
        "seat_events": [
            {"id": str(e.id), "delta": e.delta, "reason": e.reason, "at": e.created_at.isoformat(),
             "by_platform": e.actor_user_id is None}
            for e in seat_events
        ],
    })


class SaFacilityPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=2)
    status: Literal["active", "suspended", "archived"] | None = None


@router.patch("/facilities/{facility_id}")
def sa_patch_facility(facility_id: uuid.UUID, body: SaFacilityPatchIn, ctx: SuperAuth, request: Request, db: SystemDB):
    """تفعيل/تعليق/أرشفة المنشأة — يسري فوراً على دخول أدمنها ودكاترتها (ترابط المنصات §٠.١)."""
    require_cap(ctx, "facilities.write")
    facility = _get_facility(db, facility_id)
    changes: dict[str, str] = {}
    if body.name is not None and body.name != facility.name:
        changes["name"] = body.name
        facility.name = body.name
    if body.status is not None and body.status != facility.status:
        if body.status in ("suspended", "archived"):
            require_reauth(ctx, request)  # إجراء حسّاس — DOC-20 §١.٣
        changes["status"] = body.status
        facility.status = body.status
    if changes:
        sa_audit(db, ctx, "sa.facility_updated", "facility", facility.id,
                 facility_id=facility.id, meta=changes)
    return ok({"id": str(facility.id), "name": facility.name, "status": facility.status})


class SaSubscriptionPatchIn(BaseModel):
    plan_code: str | None = None
    seats_total: int | None = Field(default=None, ge=1, le=500)  # عدد الدكاترة (§٠.١ تعديل ٢)


@router.patch("/facilities/{facility_id}/subscription")
def sa_patch_subscription(facility_id: uuid.UUID, body: SaSubscriptionPatchIn, ctx: SuperAuth, db: SystemDB):
    """تغيير دورة الفوترة/عدد الدكاترة من المنصة — بلا فوترة تلقائية (الفاتورة فعل صريح)."""
    require_cap(ctx, "facilities.write")
    facility = _get_facility(db, facility_id)
    subscription = db.execute(
        select(Subscription).where(Subscription.facility_id == facility.id)
    ).scalar_one_or_none()
    if subscription is None:
        raise MedifyError("MDF-4041")
    changes: dict[str, object] = {}

    if body.plan_code is not None and body.plan_code != subscription.plan:
        plan = db.execute(select(Plan).where(Plan.code == body.plan_code)).scalar_one_or_none()
        if plan is None or not plan.is_active:
            raise MedifyError("MDF-4041", details={"reason": "plan_not_found_or_inactive"})
        changes["plan"] = {"from": subscription.plan, "to": body.plan_code}
        subscription.plan = body.plan_code

    if body.seats_total is not None and body.seats_total != subscription.seats_total:
        used = seats_used(db, facility.id)
        if body.seats_total < used:
            raise MedifyError("MDF-4221", details={"seats_used": used, "requested": body.seats_total})
        delta = body.seats_total - subscription.seats_total
        subscription.seats_total = body.seats_total
        db.add(SeatEvent(
            subscription_id=subscription.id,
            delta=delta,
            reason="expand" if delta > 0 else "reduce",
            actor_user_id=None,  # NULL = فعل المنصة
        ))
        changes["seats_delta"] = delta

    if changes:
        sa_audit(db, ctx, "sa.subscription_updated", "subscription", subscription.id,
                 facility_id=facility.id, meta=changes)
    return ok({
        "plan": subscription.plan,
        "seats_total": subscription.seats_total,
        "seats_used": seats_used(db, facility.id),
    })


# ════════════════ مستخدمو المنشأة (أدمن + دكاترة) ════════════════

class SaUserCreateIn(BaseModel):
    role: Literal["admin", "doctor"]
    full_name: str = Field(min_length=2)
    username: str = Field(min_length=3)
    password: str = Field(min_length=8)
    email: EmailStr | None = None       # إلزامي للأدمن (قناة الاستعادة)
    specialty: str | None = None        # إلزامي للدكتور
    clinic_id: uuid.UUID | None = None  # إلزامي للدكتور


@router.post("/facilities/{facility_id}/users", status_code=201)
def sa_create_user(facility_id: uuid.UUID, body: SaUserCreateIn, ctx: SuperAuth, db: SystemDB):
    require_cap(ctx, "users.write")
    facility = _get_facility(db, facility_id)
    if body.role == "admin" and body.email is None:
        raise MedifyError("MDF-4041", details={"reason": "admin_email_required"})
    if body.role == "doctor":
        if body.specialty is None or body.clinic_id is None:
            raise MedifyError("MDF-4041", details={"reason": "doctor_specialty_clinic_required"})
        clinic = db.execute(
            select(Clinic).where(Clinic.id == body.clinic_id, Clinic.facility_id == facility.id)
        ).scalar_one_or_none()
        if clinic is None:
            raise MedifyError("MDF-4041", details={"reason": "clinic_not_in_facility"})
        subscription = db.execute(
            select(Subscription).where(Subscription.facility_id == facility.id)
        ).scalar_one_or_none()
        if subscription is None:
            raise MedifyError("MDF-4041")
        if seats_used(db, facility.id) >= subscription.seats_total:
            raise MedifyError("MDF-4221", details={"seats_total": subscription.seats_total})
    duplicate = db.execute(
        select(User).where(User.facility_id == facility.id, User.username == body.username)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise MedifyError("MDF-4041", details={"reason": "username_taken"})
    user = User(
        facility_id=facility.id,
        role=body.role,
        full_name=body.full_name,
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        specialty=body.specialty if body.role == "doctor" else None,
        clinic_id=body.clinic_id if body.role == "doctor" else None,
        is_active=True,
    )
    db.add(user)
    db.flush()
    if body.role == "doctor":
        subscription = db.execute(
            select(Subscription).where(Subscription.facility_id == facility.id)
        ).scalar_one()
        db.add(SeatEvent(subscription_id=subscription.id, delta=0, reason="activate_dr", actor_user_id=None))
    sa_audit(db, ctx, "sa.user_created", "user", user.id, facility_id=facility.id,
             meta={"role": body.role, "username": body.username})
    return ok({"id": str(user.id), "username": user.username, "role": user.role})


def _get_platform_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None:
        raise MedifyError("MDF-4041")
    return user


class SaUserPatchIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2)
    email: EmailStr | None = None
    specialty: str | None = None
    is_active: bool | None = None


@router.patch("/users/{user_id}")
def sa_patch_user(user_id: uuid.UUID, body: SaUserPatchIn, ctx: SuperAuth, db: SystemDB):
    """تعديل/تفعيل/تعطيل أي مستخدم — تعطيل الدكتور يحرر مقعده فوراً في الطبقات الثلاث."""
    require_cap(ctx, "users.write")
    user = _get_platform_user(db, user_id)
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.email is not None:
        user.email = body.email
    if body.specialty is not None and user.role == "doctor":
        user.specialty = body.specialty
    if body.is_active is not None and body.is_active != user.is_active:
        if body.is_active and user.role == "doctor":
            subscription = db.execute(
                select(Subscription).where(Subscription.facility_id == user.facility_id)
            ).scalar_one_or_none()
            if subscription is not None and seats_used(db, user.facility_id) >= subscription.seats_total:
                raise MedifyError("MDF-4221", details={"seats_total": subscription.seats_total})
        user.is_active = body.is_active
        if user.role == "doctor":
            subscription = db.execute(
                select(Subscription).where(Subscription.facility_id == user.facility_id)
            ).scalar_one_or_none()
            if subscription is not None:
                db.add(SeatEvent(
                    subscription_id=subscription.id,
                    delta=0,
                    reason="activate_dr" if body.is_active else "deactivate_dr",
                    actor_user_id=None,
                ))
    sa_audit(db, ctx, "sa.user_updated", "user", user.id, facility_id=user.facility_id,
             meta=body.model_dump(exclude_none=True, mode="json"))
    return ok({"id": str(user.id), "is_active": user.is_active})


@router.post("/users/{user_id}/reset-password")
def sa_reset_user_password(user_id: uuid.UUID, ctx: SuperAuth, db: SystemDB):
    """كلمة مرور مؤقتة لأي مستخدم — تُعرض مرة واحدة (نمط FR-204)."""
    require_cap(ctx, "users.write")
    user = _get_platform_user(db, user_id)
    temp_password = "Md-" + secrets.token_urlsafe(8)
    user.password_hash = hash_password(temp_password)
    sa_audit(db, ctx, "sa.user_password_reset", "user", user.id, facility_id=user.facility_id)
    return ok({"temporary_password": temp_password})


# ════════ الباقات — تكلفة الدكتور لكل دورة (تعديل مالك §٠.١) + مميزاتها (قرار مالك 2026-08-03) ════════

def _plan_out(db: Session, plan: Plan) -> dict:
    facilities_count = db.execute(
        select(func.count(Subscription.id)).where(Subscription.plan == plan.code)
    ).scalar_one()
    features = plan_features(plan)
    return {
        "id": str(plan.id),
        "code": plan.code,
        "name_ar": plan.name_ar,
        "name_en": plan.name_en,
        "seat_price_sar": str(plan.seat_price_sar),
        "billing_cycle": plan.billing_cycle,
        "is_active": plan.is_active,
        "facilities_count": facilities_count,
        "features": features,
        # عدّاد الاختيارية المفعّلة (الأساسية خارج العدّ — ليست خياراً)
        "features_on": sum(1 for key, on in features.items() if on and key not in CORE_KEYS),
        "features_total": len(features) - len(CORE_KEYS),
    }


@router.get("/features")
def sa_feature_catalog(ctx: SuperAuth, db: SystemDB):
    """كتالوج المميزات القابلة للضم للباقات — مصدره الكود (`app/features.py`)."""
    return ok({"groups": [{"code": c, "name_ar": ar, "name_en": en} for c, ar, en in FEATURE_GROUPS],
               "features": catalog_out()})


class SaPlanFeaturesIn(BaseModel):
    features: dict[str, bool]


@router.put("/plans/{plan_id}/features")
def sa_set_plan_features(plan_id: uuid.UUID, body: SaPlanFeaturesIn, ctx: SuperAuth, request: Request, db: SystemDB):
    """ضبط ما تُظهره الباقة للدكتور — تسري فوراً على كل منشأة عليها (مبدأ الترابط، DOC-20 تعديل ١).

    الخريطة تُستبدل كاملة (PUT لا PATCH): ما لم يُذكر يعود لافتراض الكتالوج، فلا تُخزَّن
    مفاتيح ميتة. الأساسية تُتجاهل إن أُرسلت — لا تُطفأ بأي حال.
    """
    require_cap(ctx, "plans.write")  # owner حصراً (DOC-20 §١.٢)
    require_reauth(ctx, request)     # تغيير ما يراه الأطباء — إجراء حسّاس كتغيير السعر
    plan = db.execute(select(Plan).where(Plan.id == plan_id)).scalar_one_or_none()
    if plan is None:
        raise MedifyError("MDF-4041")

    unknown = sorted(set(body.features) - set(FEATURE_BY_KEY))
    if unknown:
        raise MedifyError("MDF-4041", details={"reason": "unknown_feature_keys", "keys": unknown})

    before = plan_features(plan)
    stored = {key: value for key, value in body.features.items() if key not in CORE_KEYS}
    plan.features = stored
    after = plan_features(plan)
    changed = {key: {"from": before[key], "to": after[key]} for key in after if before[key] != after[key]}
    if changed:
        sa_audit(db, ctx, "sa.plan_features_updated", "plan", plan.id,
                 meta={"code": plan.code, "changed": changed})
    return ok(_plan_out(db, plan))


@router.get("/plans")
def sa_list_plans(ctx: SuperAuth, db: SystemDB):
    plans = db.execute(select(Plan).order_by(Plan.created_at)).scalars().all()
    return ok([_plan_out(db, plan) for plan in plans])


class SaPlanCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    name_ar: str = Field(min_length=2)
    name_en: str = Field(min_length=2)
    seat_price_sar: Decimal = Field(ge=0, le=Decimal("1000000"))  # تكلفة الدكتور
    billing_cycle: Literal["monthly", "yearly"] = "monthly"


@router.post("/plans", status_code=201)
def sa_create_plan(body: SaPlanCreateIn, ctx: SuperAuth, request: Request, db: SystemDB):
    require_cap(ctx, "plans.write")  # owner حصراً (DOC-20 §١.٢)
    require_reauth(ctx, request)
    duplicate = db.execute(select(Plan).where(Plan.code == body.code)).scalar_one_or_none()
    if duplicate is not None:
        raise MedifyError("MDF-4041", details={"reason": "plan_code_taken"})
    plan = Plan(
        code=body.code,
        name_ar=body.name_ar,
        name_en=body.name_en,
        seat_price_sar=body.seat_price_sar,
        billing_cycle=body.billing_cycle,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    sa_audit(db, ctx, "sa.plan_created", "plan", plan.id,
             meta={"code": plan.code, "doctor_price_sar": str(plan.seat_price_sar)})
    return ok(_plan_out(db, plan))


class SaPlanPatchIn(BaseModel):
    name_ar: str | None = Field(default=None, min_length=2)
    name_en: str | None = Field(default=None, min_length=2)
    seat_price_sar: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000"))
    is_active: bool | None = None


@router.patch("/plans/{plan_id}")
def sa_patch_plan(plan_id: uuid.UUID, body: SaPlanPatchIn, ctx: SuperAuth, request: Request, db: SystemDB):
    """تعديل تكلفة الدكتور (الرمز ثابت) — يسري على الفواتير اللاحقة فقط."""
    require_cap(ctx, "plans.write")
    plan = db.execute(select(Plan).where(Plan.id == plan_id)).scalar_one_or_none()
    if plan is None:
        raise MedifyError("MDF-4041")
    changes: dict[str, object] = {}
    if body.seat_price_sar is not None and body.seat_price_sar != plan.seat_price_sar:
        require_reauth(ctx, request)  # تغيير سعر — إجراء حسّاس (DOC-20 §١.٣)
        changes["doctor_price_sar"] = {"from": str(plan.seat_price_sar), "to": str(body.seat_price_sar)}
        plan.seat_price_sar = body.seat_price_sar
    if body.name_ar is not None:
        plan.name_ar = body.name_ar
    if body.name_en is not None:
        plan.name_en = body.name_en
    if body.is_active is not None and body.is_active != plan.is_active:
        changes["is_active"] = body.is_active
        plan.is_active = body.is_active
    if changes:
        sa_audit(db, ctx, "sa.plan_updated", "plan", plan.id, meta={"code": plan.code, **changes})
    return ok(_plan_out(db, plan))


# ════════════════ الفواتير والمدفوعات ════════════════

@router.get("/invoices")
def sa_list_invoices(
    ctx: SuperAuth, db: SystemDB,
    status: str = "", facility_id: str = "", page: int = 1, per_page: int = 25,
):
    page, per_page = pagination(page, per_page)
    base = select(Invoice)
    if status in ("due", "paid", "overdue", "void"):
        base = base.where(Invoice.status == status)
    if facility_id:
        try:
            base = base.where(Invoice.facility_id == uuid.UUID(facility_id))
        except ValueError:
            raise MedifyError("MDF-4041", details={"reason": "bad_facility_id"})
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(
        base.order_by(Invoice.issued_at.desc()).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()
    names = dict(db.execute(
        select(Facility.id, Facility.name).where(Facility.id.in_({r.facility_id for r in rows}))
    ).all()) if rows else {}
    return paginated(
        [_invoice_out(invoice, names.get(invoice.facility_id, "")) for invoice in rows],
        total, page, per_page,
    )


class SaInvoiceCreateIn(BaseModel):
    seats: int | None = Field(default=None, ge=1, le=500)  # الافتراضي: عدد الدكاترة النشطين


@router.post("/facilities/{facility_id}/invoices", status_code=201)
def sa_issue_invoice(facility_id: uuid.UUID, body: SaInvoiceCreateIn, ctx: SuperAuth, db: SystemDB):
    """إصدار فاتورة دورة — المبلغ = عدد الدكاترة النشطين × تكلفة الدكتور (أو عدد صريح)."""
    require_cap(ctx, "invoices.write")
    facility = _get_facility(db, facility_id)
    subscription = db.execute(
        select(Subscription).where(Subscription.facility_id == facility.id)
    ).scalar_one_or_none()
    if subscription is None:
        raise MedifyError("MDF-4041")
    seats = body.seats if body.seats is not None else seats_used(db, facility.id)
    if seats < 1:
        raise MedifyError("MDF-4221", details={"reason": "no_active_doctors"})
    invoice = issue_invoice(db, subscription, seats)
    sa_audit(db, ctx, "sa.invoice_issued", "invoice", invoice.id, facility_id=facility.id,
             meta={"seats": seats, "number": invoice.number})
    return ok(_invoice_out(invoice, facility.name))


class SaInvoicePatchIn(BaseModel):
    status: Literal["paid", "void", "overdue", "due"]


@router.patch("/invoices/{invoice_id}")
def sa_patch_invoice(invoice_id: uuid.UUID, body: SaInvoicePatchIn, ctx: SuperAuth, db: SystemDB):
    """تسوية يدوية: paid تسجل السداد وترفع التعليق إن لم تبقَ متأخرات؛ void إلغاء؛ due/overdue تصنيف."""
    require_cap(ctx, "invoices.write")
    invoice = db.execute(select(Invoice).where(Invoice.id == invoice_id)).scalar_one_or_none()
    if invoice is None:
        raise MedifyError("MDF-4041")
    if invoice.status == body.status:
        return ok(_invoice_out(invoice))
    if invoice.status == "paid":
        # لا تراجع عن سداد مسجل — مسار الاسترداد خارج النطاق
        raise MedifyError("MDF-4228", details={"reason": "already_paid"})
    if invoice.status == "void":
        raise MedifyError("MDF-4228", details={"reason": "void_invoice"})

    invoice.status = body.status
    meta: dict[str, object] = {"number": invoice.number, "to": body.status}
    if body.status == "paid":
        invoice.paid_at = dt.datetime.now(dt.timezone.utc)
        invoice.provider_ref = invoice.provider_ref or f"manual_{uuid.uuid4().hex[:10]}"
        meta["provider_ref"] = invoice.provider_ref
        facility = db.execute(select(Facility).where(Facility.id == invoice.facility_id)).scalar_one()
        remaining_overdue = db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.facility_id == facility.id,
                Invoice.status == "overdue",
                Invoice.id != invoice.id,
            )
        ).scalar_one()
        if facility.status == "suspended" and remaining_overdue == 0:
            facility.status = "active"
            sa_audit(db, ctx, "facility.suspension_lifted", "facility", facility.id,
                     facility_id=facility.id, meta={"invoice": invoice.number})
    sa_audit(db, ctx, "sa.invoice_status_changed", "invoice", invoice.id,
             facility_id=invoice.facility_id, meta=meta)
    return ok(_invoice_out(invoice))


# ════════════════ إعدادات الذكاء الاصطناعي (توجيه مالك 2026-08-01) ════════════════

def _ai_settings_out(db: Session) -> dict:
    from ...services.ai_models import list_google_models, stored_gemini_model

    s = get_settings()
    selected = stored_gemini_model(db)
    models, source = list_google_models()
    return {
        "llm_engine": s.llm_engine,
        "stt_engine": s.stt_engine,
        "default_model": s.gemini_model,               # افتراضي البيئة (GEMINI_MODEL)
        "selected_model": selected,                    # تجاوز المنصة — None = يسري الافتراضي
        "effective_model": selected or s.gemini_model,
        "stt_model": s.gemini_stt_model or selected or s.gemini_model,
        "models": models,
        "models_source": source,                       # live = من Google API | fallback = كتالوج ثابت
    }


@router.get("/settings/ai")
def sa_ai_settings(ctx: SuperAuth, db: SystemDB):
    """النموذج الفعلي + قائمة نماذج قوقل المتاحة للحساب — قراءة لكل الدرجات."""
    return ok(_ai_settings_out(db))


class SaAiSettingsIn(BaseModel):
    # None = حذف التجاوز والعودة لافتراضي البيئة — النمط يسمح بكل معرفات نماذج قوقل
    gemini_model: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-/]*$")


@router.patch("/settings/ai")
def sa_update_ai_settings(body: SaAiSettingsIn, ctx: SuperAuth, request: Request, db: SystemDB):
    """تبديل نموذج قوقل للمنصة كلها — يسري فوراً (إعادة بناء محركي llm/stt) دون نشر."""
    from ...pipelines.llm import reset_llm_cache
    from ...pipelines.stt import reset_stt_cache
    from ...services.ai_models import set_gemini_model, stored_gemini_model

    require_cap(ctx, "settings.write")  # owner حصراً
    require_reauth(ctx, request)        # تغيير نموذج المنصة — إجراء حسّاس (DOC-20 §١.٣)
    previous = stored_gemini_model(db)
    if body.gemini_model != previous:
        set_gemini_model(db, body.gemini_model, ctx.admin_id)
        db.flush()
        reset_llm_cache()
        reset_stt_cache()
        sa_audit(db, ctx, "sa.ai_model_updated", "platform_setting", "ai.gemini_model",
                 meta={"from": previous or "(default)", "to": body.gemini_model or "(default)"})
    return ok(_ai_settings_out(db))


# ════════════════ عتبات ثقة التفريغ (التحصين م11) ════════════════

class SaSttThresholdsIn(BaseModel):
    low: float = Field(gt=0.0, le=1.0)
    medium: float = Field(gt=0.0, le=1.0)


@router.get("/settings/stt-confidence")
def sa_stt_thresholds(ctx: SuperAuth, db: SystemDB):
    """عتبات إبراز الثقة المنخفضة — تسري فوراً على كل شاشات المراجعة بلا نشر."""
    from ...services.stt_confidence import DEFAULT_THRESHOLDS, resolve_thresholds

    return ok({"thresholds": resolve_thresholds(), "defaults": DEFAULT_THRESHOLDS})


@router.patch("/settings/stt-confidence")
def sa_update_stt_thresholds(body: SaSttThresholdsIn, ctx: SuperAuth, request: Request, db: SystemDB):
    from ...services.stt_confidence import set_thresholds

    require_cap(ctx, "settings.write")  # owner حصراً
    if body.low > body.medium:
        raise MedifyError("MDF-4225", details={"reason": "low_must_not_exceed_medium"})
    value = set_thresholds(db, body.low, body.medium, ctx.admin_id)
    sa_audit(db, ctx, "sa.stt_thresholds_updated", "platform_setting", "stt.confidence_thresholds",
             meta=value)
    return ok({"thresholds": value})


# ════════════════ السجل المرجعي للأكواد — ملفات الأكواد المعتمدة (قرار مالك 2026-08-02) ════════════════

REGISTRY_FILE_MAX_BYTES = 25 * 1024 * 1024  # ملف CHI الرسمي ~2MB — سقف مريح


@router.get("/registry")
def sa_registry_overview(ctx: SuperAuth, db: SystemDB):
    """حالة السجل لكل نظام (SBS/ICD10AM/ACHI/SFDA/GMDN): الأعداد والإصدارات وآخر تحديث
    وحالة الإنفاذ (سجل فارغ = لا تحقق لذلك النظام) — قراءة لكل الدرجات."""
    from ...services.registry_import import registry_overview

    return ok({"systems": registry_overview(db)})


@router.post("/registry/import")
async def sa_registry_import(
    ctx: SuperAuth,
    request: Request,
    db: SystemDB,
    file: UploadFile,
    system: Annotated[str, Form()],
    version: Annotated[str, Form(min_length=2, max_length=80)],
    dry_run: Annotated[bool, Form()] = False,
):
    """رفع ملف أكواد معتمد (xlsx من CHI أو CSV عام) واستيراده — owner حصراً.

    dry_run=true: معاينة الأعداد بلا كتابة (لا إعادة مصادقة).
    dry_run=false: الاعتماد والنشر الفعلي — إجراء حسّاس (TOTP) ويُدوَّن في سجل المنصة.
    """
    from ...services.registry_import import REGISTRY_SYSTEMS, import_codes, parse_registry_file

    require_cap(ctx, "registry.write")
    if system not in REGISTRY_SYSTEMS:
        raise MedifyError("MDF-4041", details={"system": system})
    if not dry_run:
        require_reauth(ctx, request)  # نشر مرجع ترميز المنصة كلها — حسّاس (DOC-20 §١.٣)

    content = await file.read()
    if len(content) > REGISTRY_FILE_MAX_BYTES:
        raise MedifyError("MDF-4225", details={"reason": "file_too_large", "max_bytes": REGISTRY_FILE_MAX_BYTES})
    try:
        rows = parse_registry_file(file.filename or "", content)
        inserted, updated = import_codes(db, system, version, rows)
    except ValueError as exc:
        raise MedifyError("MDF-4225", details={"reason": "invalid_registry_file", "error": str(exc)}) from exc

    if dry_run:
        db.rollback()  # معاينة فقط — لا كتابة ولا تدوين
        return ok({"dry_run": True, "system": system, "version": version,
                   "inserted": inserted, "updated": updated})

    db.flush()
    sa_audit(db, ctx, "sa.registry_imported", "registry_codes", system,
             meta={"system": system, "version": version, "file": file.filename,
                   "inserted": inserted, "updated": updated})
    from ...services.registry_import import registry_overview

    return ok({"dry_run": False, "system": system, "version": version,
               "inserted": inserted, "updated": updated,
               "systems": registry_overview(db)})


@router.delete("/registry/{system}")
def sa_registry_clear(system: str, ctx: SuperAuth, request: Request, db: SystemDB):
    """إزالة سجل نظامٍ كاملاً — يوقف التحقق لذلك النظام فوراً (يعود سلوك ما قبل التحميل).

    owner حصراً + إعادة مصادقة — يُدوَّن في سجل المنصة."""
    from ...models import RegistryCode
    from ...services.registry_import import REGISTRY_SYSTEMS, registry_overview

    require_cap(ctx, "registry.write")
    if system not in REGISTRY_SYSTEMS:
        raise MedifyError("MDF-4041", details={"system": system})
    require_reauth(ctx, request)

    removed = db.execute(
        sa_delete(RegistryCode).where(RegistryCode.code_system == system)
    ).rowcount
    if removed == 0:
        raise MedifyError("MDF-4041", details={"system": system, "reason": "registry_empty"})
    sa_audit(db, ctx, "sa.registry_cleared", "registry_codes", system,
             meta={"system": system, "removed": removed})
    return ok({"system": system, "removed": removed, "systems": registry_overview(db)})


# ════════════════ البرومبتات (FR-500+) ════════════════

class SaPromptIn(BaseModel):
    """حفظ إصدار جديد من برومبت ديفولت."""
    prompt_content: str = Field(min_length=10)
    version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")


@router.get("/prompts")
def sa_list_prompts(ctx: SuperAuth, db: SystemDB):
    """قائمة جميع البرومبتات الديفولت مع إصداراتها."""
    from ...models import PlatformDefaultPrompt

    prompts = db.execute(
        select(PlatformDefaultPrompt).order_by(
            PlatformDefaultPrompt.template_type,
            PlatformDefaultPrompt.version.desc()
        )
    ).scalars().all()

    by_type = {}
    for p in prompts:
        if p.template_type not in by_type:
            by_type[p.template_type] = []
        by_type[p.template_type].append({
            "id": str(p.id),
            "version": p.version,
            "is_active": p.is_active,
            "created_at": p.created_at.isoformat(),
            "updated_by": str(p.updated_by) if p.updated_by else None,
        })

    return ok(by_type)


@router.get("/prompts/{template_type}")
def sa_get_prompt(template_type: str, ctx: SuperAuth, db: SystemDB):
    """معاينة البرومبت النشط لنوع قالب معين."""
    from ...models import PlatformDefaultPrompt

    prompt = db.execute(
        select(PlatformDefaultPrompt).where(
            PlatformDefaultPrompt.template_type == template_type,
            PlatformDefaultPrompt.is_active == True
        )
    ).scalar_one_or_none()

    if prompt is None:
        raise MedifyError("MDF-4041", details={"template_type": template_type, "reason": "not_found"})

    return ok({
        "id": str(prompt.id),
        "template_type": prompt.template_type,
        "version": prompt.version,
        "content": prompt.prompt_content,
        "is_active": prompt.is_active,
        "created_at": prompt.created_at.isoformat(),
    })


@router.post("/prompts/{template_type}")
def sa_create_prompt(template_type: str, body: SaPromptIn, ctx: SuperAuth, db: SystemDB):
    """حفظ إصدار جديد من برومبت ديفولت (لا يُفعّل تلقائياً)."""
    from ...models import PlatformDefaultPrompt

    require_cap(ctx, "prompts.write")

    # التحقق من أن الإصدار لا يوجد بالفعل
    existing = db.execute(
        select(PlatformDefaultPrompt).where(
            PlatformDefaultPrompt.template_type == template_type,
            PlatformDefaultPrompt.version == body.version
        )
    ).scalar_one_or_none()

    if existing is not None:
        raise MedifyError("MDF-4225", details={"template_type": template_type, "version": body.version,
                                               "reason": "version_already_exists"})

    prompt = PlatformDefaultPrompt(
        template_type=template_type,
        prompt_content=body.prompt_content,
        version=body.version,
        is_active=False,  # يتطلب تفعيل منفصل
        created_by=ctx.admin_id,
    )
    db.add(prompt)
    db.flush()

    sa_audit(db, ctx, "sa.prompt_created", "platform_default_prompts", str(prompt.id),
             meta={"template_type": template_type, "version": body.version})

    return ok({
        "id": str(prompt.id),
        "template_type": prompt.template_type,
        "version": prompt.version,
        "is_active": False,
    })


@router.patch("/prompts/{template_type}/activate")
def sa_activate_prompt(template_type: str, version: str, ctx: SuperAuth, request: Request, db: SystemDB):
    """تفعيل إصدار من برومبت (يُلغي تفعيل الإصدارات السابقة) — requires reauth."""
    from ...models import PlatformDefaultPrompt

    require_cap(ctx, "prompts.write")
    require_reauth(ctx, request)

    # البحث عن الإصدار المطلوب
    target = db.execute(
        select(PlatformDefaultPrompt).where(
            PlatformDefaultPrompt.template_type == template_type,
            PlatformDefaultPrompt.version == version
        )
    ).scalar_one_or_none()

    if target is None:
        raise MedifyError("MDF-4041", details={"template_type": template_type, "version": version})

    # إلغاء تفعيل الإصدارات السابقة
    db.execute(
        sa_delete(PlatformDefaultPrompt.__table__).where(
            PlatformDefaultPrompt.template_type == template_type,
            PlatformDefaultPrompt.is_active == True
        )
    )
    # تفعيل الإصدار الجديد
    target.is_active = True
    target.updated_by = ctx.admin_id

    sa_audit(db, ctx, "sa.prompt_activated", "platform_default_prompts", str(target.id),
             meta={"template_type": template_type, "version": version})

    return ok({
        "id": str(target.id),
        "template_type": target.template_type,
        "version": target.version,
        "is_active": True,
    })
