"""اعتماديات المصادقة والأدوار — الطبقة الأولى من الدفاع الثلاثي (DOC-06 §١)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db, get_system_db, set_rls_context
from .errors import MedifyError
from .models import PlatformAdmin, User
from .security import decode_token


@dataclass
class AuthContext:
    user_id: uuid.UUID
    facility_id: uuid.UUID
    role: str  # admin | doctor
    user: User


@dataclass
class SuperAdminContext:
    admin_id: uuid.UUID
    username: str
    role: str  # owner | ops | finance | support | read_only (DOC-20 §١.٢)
    admin: PlatformAdmin
    ip: str | None = None


# قدرات الدرجات — DOC-20 §١.٢: كل درجة أقل من التي فوقها؛ الكتالوج/الأسعار والحسابات للـowner حصراً
GRADE_CAPS: dict[str, frozenset[str]] = {
    "owner": frozenset({"facilities.write", "users.write", "invoices.write", "plans.write", "admins.manage", "security"}),
    "ops": frozenset({"facilities.write", "users.write", "invoices.write"}),
    "finance": frozenset({"invoices.write"}),
    "support": frozenset(),
    "read_only": frozenset(),
}


def require_cap(ctx: SuperAdminContext, cap: str) -> None:
    """الحارس المزدوج (ب): الدرجة تسمح بالفعل — تُحقن من القاعدة لا من الرمز (DOC-20 §١.٢)."""
    if cap not in GRADE_CAPS.get(ctx.role, frozenset()):
        raise MedifyError("MDF-4031", details={"grade": ctx.role, "required": cap})


# مسارات مسموحة قبل إتمام تفعيل 2FA (الإعداد نفسه + الهوية)
_SA_2FA_EXEMPT_PREFIXES = ("/api/v1/sa/auth/", "/api/v1/sa/me")


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise MedifyError("MDF-4012")
    return auth[7:]


def authenticated(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> AuthContext:
    """تتحقق من JWT وتضبط جلسة RLS (SET LOCAL) — كل النقاط المسجلة تمر من هنا."""
    payload = decode_token(_bearer_token(request), "access")
    if payload.get("scope") == "platform":
        # رمز السوبر أدمن لا يفتح مسارات المنشآت — نطاقه /sa حصراً
        raise MedifyError("MDF-4031")
    user_id = uuid.UUID(payload["sub"])
    facility_id = uuid.UUID(payload["facility_id"])
    role = payload["role"]

    set_rls_context(db, facility_id, user_id, role)

    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise MedifyError("MDF-4013")
    return AuthContext(user_id=user_id, facility_id=facility_id, role=role, user=user)


def admin_only(ctx: Annotated[AuthContext, Depends(authenticated)]) -> AuthContext:
    if ctx.role != "admin":
        raise MedifyError("MDF-4031")
    return ctx


def doctor_only(ctx: Annotated[AuthContext, Depends(authenticated)]) -> AuthContext:
    if ctx.role != "doctor":
        raise MedifyError("MDF-4031")
    return ctx


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def super_admin_only(
    request: Request,
    db: Annotated[Session, Depends(get_system_db)],
) -> SuperAdminContext:
    """مصادقة السوبر أدمن — محرك النظام (يتجاوز RLS)؛ ترفض رموز المنشآت (admin/doctor).

    فرض 2FA (DOC-20 §١.٣): على الإنتاج لا يُفتح الكونسول قبل تفعيل TOTP —
    تُستثنى مسارات الهوية والإعداد نفسها (/sa/auth/*, /sa/me*).
    """
    payload = decode_token(_bearer_token(request), "access")
    if payload.get("role") != "super_admin" or payload.get("scope") != "platform":
        raise MedifyError("MDF-4031")
    admin = db.execute(
        select(PlatformAdmin).where(PlatformAdmin.id == uuid.UUID(payload["sub"]))
    ).scalar_one_or_none()
    if admin is None or not admin.is_active:
        raise MedifyError("MDF-4013")

    from .config import get_settings
    if (
        get_settings().environment == "production"
        and not admin.totp_enabled
        and not request.url.path.startswith(_SA_2FA_EXEMPT_PREFIXES)
    ):
        raise MedifyError("MDF-4015", details={"reason": "2fa_setup_required"})

    return SuperAdminContext(
        admin_id=admin.id, username=admin.username, role=admin.role, admin=admin, ip=_client_ip(request),
    )


def require_reauth(ctx: SuperAdminContext, request: Request) -> None:
    """إعادة مصادقة للإجراءات الحسّاسة (DOC-20 §١.٣): رمز TOTP حي في ترويسة X-SA-Reauth.

    تُفرض فقط عندما يكون 2FA مفعّلاً للحساب (قبل التفعيل لا معنى لها).
    """
    if not ctx.admin.totp_enabled:
        return
    from .totp import verify_totp
    code = request.headers.get("X-SA-Reauth", "")
    secret = ctx.admin.totp_secret_encrypted
    if not code or not secret or not verify_totp(secret, code):
        raise MedifyError("MDF-4015", details={"reason": "reauth_required"})


DB = Annotated[Session, Depends(get_db)]
Auth = Annotated[AuthContext, Depends(authenticated)]
AdminAuth = Annotated[AuthContext, Depends(admin_only)]
DoctorAuth = Annotated[AuthContext, Depends(doctor_only)]
SuperAuth = Annotated[SuperAdminContext, Depends(super_admin_only)]


def pagination(page: int = 1, per_page: int = 25) -> tuple[int, int]:
    """ترقيم DOC-05 §١ — الحد الأقصى 100."""
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    return page, per_page
