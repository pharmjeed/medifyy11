"""المصادقة والجلسة — DOC-05 §٢ (المسارات العامة تعمل بمحرك النظام — D-19)."""
from __future__ import annotations

import datetime as dt
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...analytics import track
from ...audit import audit
from ...config import get_settings
from ...db import get_system_db
from ...deps import Auth
from ...envelope import ok
from ...errors import MedifyError
from ...models import Clinic, Facility, PasswordResetToken, User
from ...notify import _send_email_mock
from ...security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    lockout,
    verify_password,
)

router = APIRouter()

SystemDB = Annotated[Session, Depends(get_system_db)]

REFRESH_COOKIE = "medify_refresh"


class LoginIn(BaseModel):
    facility: str = Field(min_length=1)  # السجل التجاري أو اسم المنشأة
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


def _find_facility(db: Session, key: str) -> Facility | None:
    return db.execute(
        select(Facility).where((Facility.commercial_reg == key) | (Facility.name == key))
    ).scalar_one_or_none()


def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        secure=s.environment != "dev",
        samesite="lax",
        max_age=s.refresh_token_days * 86400,
        path="/api/v1/auth",
    )


@router.post("/auth/login")
def login(body: LoginIn, response: Response, db: SystemDB):
    if lockout.is_locked(body.facility, body.username):
        raise MedifyError("MDF-4011", details={"locked": True})

    facility = _find_facility(db, body.facility)
    user = None
    if facility is not None:
        user = db.execute(
            select(User).where(User.facility_id == facility.id, User.username == body.username)
        ).scalar_one_or_none()

    if user is None or not verify_password(user.password_hash, body.password):
        lockout.record_failure(body.facility, body.username)
        if lockout.is_locked(body.facility, body.username) and facility is not None:
            audit(db, facility.id, "auth.lockout", "user", body.username, None, {"window_min": 15})
        raise MedifyError("MDF-4011")

    if not user.is_active or facility.status == "archived":
        raise MedifyError("MDF-4013")

    lockout.reset(body.facility, body.username)
    access = create_access_token(user.id, facility.id, user.role)
    refresh = create_refresh_token(user.id, facility.id, user.role)
    _set_refresh_cookie(response, refresh)
    track("session.daily_active", facility.id, user.role)
    return ok({
        "access_token": access,
        "user": {
            "id": str(user.id),
            "full_name": user.full_name,
            "role": user.role,
            "facility_id": str(facility.id),
            "facility_name": facility.name,
            "facility_status": facility.status,
        },
    })


@router.post("/auth/refresh")
def refresh_session(request: Request, response: Response, db: SystemDB):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise MedifyError("MDF-4012")
    payload = decode_token(token, "refresh")
    user = db.execute(select(User).where(User.id == payload["sub"])).scalar_one_or_none()
    if user is None or not user.is_active:
        raise MedifyError("MDF-4012")
    access = create_access_token(user.id, user.facility_id, user.role)
    _set_refresh_cookie(response, create_refresh_token(user.id, user.facility_id, user.role))
    return ok({"access_token": access})


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return ok({"logged_out": True})


@router.get("/me")
def me(ctx: Auth, db: SystemDB):
    clinic_name = None
    if ctx.user.clinic_id:
        clinic = db.execute(select(Clinic).where(Clinic.id == ctx.user.clinic_id)).scalar_one_or_none()
        clinic_name = clinic.name if clinic else None
    facility = db.execute(select(Facility).where(Facility.id == ctx.facility_id)).scalar_one()
    return ok({
        "id": str(ctx.user.id),
        "full_name": ctx.user.full_name,
        "username": ctx.user.username,
        "email": ctx.user.email,
        "role": ctx.role,
        "specialty": ctx.user.specialty,
        "clinic_id": str(ctx.user.clinic_id) if ctx.user.clinic_id else None,
        "clinic_name": clinic_name,
        "facility_id": str(ctx.facility_id),
        "facility_name": facility.name,
        "facility_status": facility.status,
    })


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@router.patch("/me/password")
def change_own_password(body: ChangePasswordIn, ctx: Auth, db: SystemDB):
    """W-005 — تغيير كلمة المرور الذاتية (DOC-06: كلمة مروره فقط عبر /me)."""
    user = db.execute(select(User).where(User.id == ctx.user_id)).scalar_one()
    if not verify_password(user.password_hash, body.current_password):
        raise MedifyError("MDF-4011")
    user.password_hash = hash_password(body.new_password)
    audit(db, ctx.facility_id, "user.password_changed", "user", user.id, ctx.user_id)
    return ok({"changed": True})


class ForgotPasswordIn(BaseModel):
    commercial_reg: str
    username: str


@router.post("/auth/forgot-password")
def forgot_password(body: ForgotPasswordIn, db: SystemDB):
    """W-206/FR-105 — استجابة عامة موحدة لا تكشف وجود الحساب."""
    facility = db.execute(
        select(Facility).where(Facility.commercial_reg == body.commercial_reg)
    ).scalar_one_or_none()
    if facility is not None:
        user = db.execute(
            select(User).where(
                User.facility_id == facility.id,
                User.username == body.username,
                User.role == "admin",
            )
        ).scalar_one_or_none()
        if user is not None and user.email:
            raw_token = secrets.token_urlsafe(32)
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hash_token(raw_token),
                    expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30),
                )
            )
            _send_email_mock(user.email, "auth.password_reset_link", {
                "reset_url": f"{get_settings().frontend_origin}/login?reset_token={raw_token}",
                "expires_minutes": 30,
            })
            audit(db, facility.id, "auth.reset_requested", "user", user.id, None)
    return ok({"message_ar": "إن كان الحساب موجوداً فسيصلك رابط الاستعادة على البريد المسجّل."})


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


@router.post("/auth/reset-password")
def reset_password(body: ResetPasswordIn, db: SystemDB):
    token_row = db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(body.token))
    ).scalar_one_or_none()
    now = dt.datetime.now(dt.timezone.utc)
    if token_row is None or token_row.used_at is not None or token_row.expires_at < now:
        raise MedifyError("MDF-4014")
    user = db.execute(select(User).where(User.id == token_row.user_id)).scalar_one()
    user.password_hash = hash_password(body.new_password)
    token_row.used_at = now
    audit(db, user.facility_id, "auth.password_reset", "user", user.id, None)
    return ok({"reset": True})
