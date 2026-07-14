"""اعتماديات المصادقة والأدوار — الطبقة الأولى من الدفاع الثلاثي (DOC-06 §١)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db, set_rls_context
from .errors import MedifyError
from .models import User
from .security import decode_token


@dataclass
class AuthContext:
    user_id: uuid.UUID
    facility_id: uuid.UUID
    role: str  # admin | doctor
    user: User


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


DB = Annotated[Session, Depends(get_db)]
Auth = Annotated[AuthContext, Depends(authenticated)]
AdminAuth = Annotated[AuthContext, Depends(admin_only)]
DoctorAuth = Annotated[AuthContext, Depends(doctor_only)]


def pagination(page: int = 1, per_page: int = 25) -> tuple[int, int]:
    """ترقيم DOC-05 §١ — الحد الأقصى 100."""
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    return page, per_page
