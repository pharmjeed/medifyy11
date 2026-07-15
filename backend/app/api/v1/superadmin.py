"""طبقة السوبر أدمن /sa — إدارة المنصة لمالك ميديفاي (قرار مالك 2026-07-15).

المبادئ:
- محرك النظام (يتجاوز RLS) — لذلك كل استعلام يقيَّد بمعرّفات صريحة.
- لا محتوى سريرياً أبداً — عدادات وتجميعات فقط (نفس قيد أدمن المنشأة في DOC-06).
- كل فعل يُدوَّن في audit_logs بمنشأته مع actor_user_id=NULL وmeta.sa=اسم السوبر أدمن.
"""
from __future__ import annotations

import datetime as dt
import logging
import secrets
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...audit import audit
from ...config import get_settings
from ...db import get_system_db
from ...deps import SuperAuth, pagination
from ...envelope import ok, paginated
from ...errors import MedifyError
from ...models import (
    Clinic,
    Facility,
    Invoice,
    Plan,
    PlatformAdmin,
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

router = APIRouter(prefix="/sa")
logger = logging.getLogger("medify.sa")

SystemDB = Annotated[Session, Depends(get_system_db)]

SA_REFRESH_COOKIE = "medify_sa_refresh"
SA_LOCKOUT_KEY = "__platform__"  # مفتاح قفل المحاولات — منفصل عن مفاتيح المنشآت


# ════════════════ المصادقة ════════════════

class SaLoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


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
        "role": "super_admin",
    }


@router.post("/auth/login")
def sa_login(body: SaLoginIn, response: Response, db: SystemDB):
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
    lockout.reset(SA_LOCKOUT_KEY, body.username)
    _set_sa_refresh_cookie(response, create_sa_refresh_token(admin.id))
    logger.info("sa.login username=%s", admin.username)
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
    logger.info("sa.password_changed username=%s", admin.username)
    return ok({"changed": True})


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
def sa_patch_facility(facility_id: uuid.UUID, body: SaFacilityPatchIn, ctx: SuperAuth, db: SystemDB):
    """تفعيل/تعليق/أرشفة المنشأة وتعديل اسمها — الأرشفة تمنع دخول كل مستخدميها (auth.login)."""
    facility = _get_facility(db, facility_id)
    changes: dict[str, str] = {}
    if body.name is not None and body.name != facility.name:
        changes["name"] = body.name
        facility.name = body.name
    if body.status is not None and body.status != facility.status:
        changes["status"] = body.status
        facility.status = body.status
    if changes:
        audit(db, facility.id, "sa.facility_updated", "facility", facility.id, None,
              {"sa": ctx.username, **changes})
    return ok({"id": str(facility.id), "name": facility.name, "status": facility.status})


class SaSubscriptionPatchIn(BaseModel):
    plan_code: str | None = None
    seats_total: int | None = Field(default=None, ge=1, le=500)


@router.patch("/facilities/{facility_id}/subscription")
def sa_patch_subscription(facility_id: uuid.UUID, body: SaSubscriptionPatchIn, ctx: SuperAuth, db: SystemDB):
    """تغيير الباقة/المقاعد من المنصة — بلا فوترة تلقائية (الفاتورة فعل صريح من السوبر أدمن)."""
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
        audit(db, facility.id, "sa.subscription_updated", "subscription", subscription.id, None,
              {"sa": ctx.username, **changes})
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
    audit(db, facility.id, "sa.user_created", "user", user.id, None,
          {"sa": ctx.username, "role": body.role, "username": body.username})
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
    """تعديل/تفعيل/تعطيل أي مستخدم (أدمن أو دكتور) — تعطيل الدكتور يحرر مقعده فوراً."""
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
    audit(db, user.facility_id, "sa.user_updated", "user", user.id, None,
          {"sa": ctx.username, **body.model_dump(exclude_none=True, mode="json")})
    return ok({"id": str(user.id), "is_active": user.is_active})


@router.post("/users/{user_id}/reset-password")
def sa_reset_user_password(user_id: uuid.UUID, ctx: SuperAuth, db: SystemDB):
    """كلمة مرور مؤقتة لأي مستخدم — تُعرض مرة واحدة (نمط FR-204)."""
    user = _get_platform_user(db, user_id)
    temp_password = "Md-" + secrets.token_urlsafe(8)
    user.password_hash = hash_password(temp_password)
    audit(db, user.facility_id, "sa.user_password_reset", "user", user.id, None, {"sa": ctx.username})
    return ok({"temporary_password": temp_password})


# ════════════════ الباقات ════════════════

def _plan_out(db: Session, plan: Plan) -> dict:
    facilities_count = db.execute(
        select(func.count(Subscription.id)).where(Subscription.plan == plan.code)
    ).scalar_one()
    return {
        "id": str(plan.id),
        "code": plan.code,
        "name_ar": plan.name_ar,
        "name_en": plan.name_en,
        "seat_price_sar": str(plan.seat_price_sar),
        "billing_cycle": plan.billing_cycle,
        "is_active": plan.is_active,
        "facilities_count": facilities_count,
    }


@router.get("/plans")
def sa_list_plans(ctx: SuperAuth, db: SystemDB):
    plans = db.execute(select(Plan).order_by(Plan.created_at)).scalars().all()
    return ok([_plan_out(db, plan) for plan in plans])


class SaPlanCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    name_ar: str = Field(min_length=2)
    name_en: str = Field(min_length=2)
    seat_price_sar: Decimal = Field(ge=0, le=Decimal("1000000"))
    billing_cycle: Literal["monthly", "yearly"] = "monthly"


@router.post("/plans", status_code=201)
def sa_create_plan(body: SaPlanCreateIn, ctx: SuperAuth, db: SystemDB):
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
    logger.info("sa.plan_created code=%s price=%s by=%s", plan.code, plan.seat_price_sar, ctx.username)
    return ok(_plan_out(db, plan))


class SaPlanPatchIn(BaseModel):
    name_ar: str | None = Field(default=None, min_length=2)
    name_en: str | None = Field(default=None, min_length=2)
    seat_price_sar: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000"))
    is_active: bool | None = None


@router.patch("/plans/{plan_id}")
def sa_patch_plan(plan_id: uuid.UUID, body: SaPlanPatchIn, ctx: SuperAuth, db: SystemDB):
    """تعديل الباقة (الرمز ثابت) — تغيير السعر يسري على الفواتير اللاحقة فقط."""
    plan = db.execute(select(Plan).where(Plan.id == plan_id)).scalar_one_or_none()
    if plan is None:
        raise MedifyError("MDF-4041")
    if body.name_ar is not None:
        plan.name_ar = body.name_ar
    if body.name_en is not None:
        plan.name_en = body.name_en
    if body.seat_price_sar is not None:
        plan.seat_price_sar = body.seat_price_sar
    if body.is_active is not None:
        plan.is_active = body.is_active
    logger.info("sa.plan_updated code=%s by=%s", plan.code, ctx.username)
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
    """إصدار فاتورة دورة — المبلغ = عدد الدكاترة النشطين × سعر مقعد الباقة (أو عدد صريح)."""
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
    audit(db, facility.id, "sa.invoice_issued", "invoice", invoice.id, None,
          {"sa": ctx.username, "seats": seats, "number": invoice.number})
    return ok(_invoice_out(invoice, facility.name))


class SaInvoicePatchIn(BaseModel):
    status: Literal["paid", "void", "overdue", "due"]


@router.patch("/invoices/{invoice_id}")
def sa_patch_invoice(invoice_id: uuid.UUID, body: SaInvoicePatchIn, ctx: SuperAuth, db: SystemDB):
    """تسوية يدوية: paid تسجل السداد وترفع التعليق إن لم تبقَ متأخرات؛ void إلغاء؛ due/overdue تصنيف."""
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
    meta: dict[str, object] = {"sa": ctx.username, "number": invoice.number, "to": body.status}
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
            audit(db, facility.id, "facility.suspension_lifted", "facility", facility.id, None,
                  {"sa": ctx.username, "invoice": invoice.number})
    audit(db, invoice.facility_id, "sa.invoice_status_changed", "invoice", invoice.id, None, meta)
    return ok(_invoice_out(invoice))
