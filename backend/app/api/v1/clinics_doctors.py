"""العيادات والدكاترة — DOC-05 §٣ (FR-200)."""
from __future__ import annotations

import datetime as dt
import secrets
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ...audit import audit
from ...deps import AdminAuth, Auth, DB, pagination
from ...envelope import ok, paginated
from ...errors import MedifyError
from ...models import Clinic, SeatEvent, User, Visit
from ...notify import notify, notify_admins
from ...security import hash_password
from ...services.billing import ensure_seat_available, get_subscription

router = APIRouter()


# ===== العيادات (FR-201) =====

@router.get("/clinics")
def list_clinics(ctx: Auth, db: DB, include_archived: bool = False):
    """الأدمن: كل عيادات المنشأة · الدكتور: عيادته فقط (DOC-06 §٢)."""
    query = select(Clinic).where(Clinic.facility_id == ctx.facility_id)
    if ctx.role == "doctor":
        query = query.where(Clinic.id == ctx.user.clinic_id)
    elif not include_archived:
        query = query.where(Clinic.archived_at.is_(None))
    clinics = db.execute(query.order_by(Clinic.created_at)).scalars().all()
    doctor_counts = dict(db.execute(
        select(User.clinic_id, func.count(User.id))
        .where(User.facility_id == ctx.facility_id, User.role == "doctor", User.is_active == True)  # noqa: E712
        .group_by(User.clinic_id)
    ).all())
    return ok([
        {
            "id": str(clinic.id),
            "name": clinic.name,
            "archived_at": clinic.archived_at.isoformat() if clinic.archived_at else None,
            "doctors_count": doctor_counts.get(clinic.id, 0),
        }
        for clinic in clinics
    ])


class ClinicIn(BaseModel):
    name: str = Field(min_length=2)


@router.post("/clinics", status_code=201)
def create_clinic(body: ClinicIn, ctx: AdminAuth, db: DB):
    clinic = Clinic(facility_id=ctx.facility_id, name=body.name)
    db.add(clinic)
    db.flush()
    audit(db, ctx.facility_id, "clinic.created", "clinic", clinic.id, ctx.user_id, {"name": body.name})
    return ok({"id": str(clinic.id), "name": clinic.name})


@router.patch("/clinics/{clinic_id}")
def update_clinic(clinic_id: uuid.UUID, body: ClinicIn, ctx: AdminAuth, db: DB):
    clinic = db.execute(select(Clinic).where(Clinic.id == clinic_id)).scalar_one_or_none()
    if clinic is None:
        raise MedifyError("MDF-4041")
    clinic.name = body.name
    audit(db, ctx.facility_id, "clinic.updated", "clinic", clinic.id, ctx.user_id)
    return ok({"id": str(clinic.id), "name": clinic.name})


@router.delete("/clinics/{clinic_id}")
def archive_clinic(clinic_id: uuid.UUID, ctx: AdminAuth, db: DB):
    """الحذف = أرشفة ناعمة (DOC-05)."""
    clinic = db.execute(select(Clinic).where(Clinic.id == clinic_id)).scalar_one_or_none()
    if clinic is None:
        raise MedifyError("MDF-4041")
    clinic.archived_at = dt.datetime.now(dt.timezone.utc)
    audit(db, ctx.facility_id, "clinic.archived", "clinic", clinic.id, ctx.user_id)
    return ok({"archived": True})


# ===== الدكاترة (FR-202/203/204) =====

@router.get("/doctors")
def list_doctors(ctx: AdminAuth, db: DB, page: int = 1, per_page: int = 50):
    page, per_page = pagination(page, per_page)
    base = select(User).where(User.facility_id == ctx.facility_id, User.role == "doctor")
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    doctors = db.execute(base.order_by(User.created_at).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    clinics = {c.id: c.name for c in db.execute(select(Clinic).where(Clinic.facility_id == ctx.facility_id)).scalars()}
    visit_counts = dict(db.execute(
        select(Visit.doctor_id, func.count(Visit.id)).where(Visit.facility_id == ctx.facility_id).group_by(Visit.doctor_id)
    ).all())
    return paginated([
        {
            "id": str(doctor.id),
            "full_name": doctor.full_name,
            "username": doctor.username,
            "specialty": doctor.specialty,
            "clinic_id": str(doctor.clinic_id) if doctor.clinic_id else None,
            "clinic_name": clinics.get(doctor.clinic_id),
            "is_active": doctor.is_active,
            "visits_count": visit_counts.get(doctor.id, 0),
        }
        for doctor in doctors
    ], total, page, per_page)


class DoctorIn(BaseModel):
    full_name: str = Field(min_length=2)
    username: str = Field(min_length=3)
    password: str = Field(min_length=8)
    specialty: str = Field(min_length=2)
    clinic_id: uuid.UUID


@router.post("/doctors", status_code=201)
def create_doctor(body: DoctorIn, ctx: AdminAuth, db: DB):
    """يفشل بـ MDF-4221 إن لم تتوفر مقاعد (FR-202) + إشعار ad.seats_exhausted."""
    try:
        ensure_seat_available(db, ctx.facility_id)
    except MedifyError as exc:
        if exc.code == "MDF-4221":
            # جلسة مستقلة — الإشعار يجب أن ينجو من rollback الطلب الفاشل (DOC-12)
            from ...db import rls_session
            with rls_session(ctx.facility_id, ctx.user_id, "admin") as side_db:
                notify_admins(side_db, ctx.facility_id, "ad.seats_exhausted", {})
        raise
    clinic = db.execute(select(Clinic).where(Clinic.id == body.clinic_id)).scalar_one_or_none()
    if clinic is None:
        raise MedifyError("MDF-4041")
    duplicate = db.execute(
        select(User).where(User.facility_id == ctx.facility_id, User.username == body.username)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise MedifyError("MDF-4041", details={"reason": "username_taken"})
    doctor = User(
        facility_id=ctx.facility_id,
        role="doctor",
        full_name=body.full_name,
        username=body.username,
        password_hash=hash_password(body.password),
        specialty=body.specialty,
        clinic_id=body.clinic_id,
        is_active=True,
    )
    db.add(doctor)
    db.flush()
    subscription = get_subscription(db, ctx.facility_id)
    db.add(SeatEvent(subscription_id=subscription.id, delta=0, reason="activate_dr", actor_user_id=ctx.user_id))
    audit(db, ctx.facility_id, "doctor.created", "user", doctor.id, ctx.user_id, {"specialty": body.specialty})
    return ok({"id": str(doctor.id), "username": doctor.username})


class DoctorPatchIn(BaseModel):
    full_name: str | None = None
    specialty: str | None = None
    clinic_id: uuid.UUID | None = None
    is_active: bool | None = None


@router.patch("/doctors/{doctor_id}")
def update_doctor(doctor_id: uuid.UUID, body: DoctorPatchIn, ctx: AdminAuth, db: DB):
    """تعديل/تفعيل/تعطيل — التعطيل يحرر المقعد فوراً (FR-203)."""
    doctor = db.execute(
        select(User).where(User.id == doctor_id, User.role == "doctor")
    ).scalar_one_or_none()
    if doctor is None:
        raise MedifyError("MDF-4041")
    if body.is_active is True and not doctor.is_active:
        ensure_seat_available(db, ctx.facility_id)
    if body.full_name is not None:
        doctor.full_name = body.full_name
    if body.specialty is not None:
        doctor.specialty = body.specialty
    if body.clinic_id is not None:
        clinic = db.execute(select(Clinic).where(Clinic.id == body.clinic_id)).scalar_one_or_none()
        if clinic is None:
            raise MedifyError("MDF-4041")
        doctor.clinic_id = body.clinic_id
    if body.is_active is not None and body.is_active != doctor.is_active:
        doctor.is_active = body.is_active
        subscription = get_subscription(db, ctx.facility_id)
        db.add(SeatEvent(
            subscription_id=subscription.id,
            delta=0,
            reason="activate_dr" if body.is_active else "deactivate_dr",
            actor_user_id=ctx.user_id,
        ))
    audit(db, ctx.facility_id, "doctor.updated", "user", doctor.id, ctx.user_id, body.model_dump(exclude_none=True, mode="json"))
    return ok({"id": str(doctor.id), "is_active": doctor.is_active})


@router.post("/doctors/{doctor_id}/reset-password")
def reset_doctor_password(doctor_id: uuid.UUID, ctx: AdminAuth, db: DB):
    """FR-204 — كلمة مرور مؤقتة (لا تغيير إجباري — قرار مالك 2026-07-14) + إشعار dr.password_reset."""
    doctor = db.execute(
        select(User).where(User.id == doctor_id, User.role == "doctor")
    ).scalar_one_or_none()
    if doctor is None:
        raise MedifyError("MDF-4041")
    temp_password = "Md-" + secrets.token_urlsafe(8)
    doctor.password_hash = hash_password(temp_password)
    notify(db, ctx.facility_id, doctor.id, "dr.password_reset", {})
    audit(db, ctx.facility_id, "doctor.password_reset", "user", doctor.id, ctx.user_id)
    return ok({"temporary_password": temp_password})
