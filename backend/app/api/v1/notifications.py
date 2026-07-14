"""مركز الإشعارات W-003 — استثناء موثق (D-22): DOC-05 لا يذكر نقطة إشعارات
بينما DOC-10/DOC-12 يفرضان المكوّن؛ نقطتان بالحد الأدنى، قراءة/تعليم قراءة للذات فقط."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from ...deps import Auth, DB, pagination
from ...envelope import ok, paginated
from ...errors import MedifyError
from ...models import Notification

router = APIRouter()


@router.get("/notifications")
def list_notifications(ctx: Auth, db: DB, page: int = 1, per_page: int = 25, unread_only: bool = False):
    page, per_page = pagination(page, per_page)
    base = select(Notification).where(Notification.user_id == ctx.user_id)
    if unread_only:
        base = base.where(Notification.read_at.is_(None))
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    unread = db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == ctx.user_id, Notification.read_at.is_(None)
        )
    ).scalar_one()
    rows = db.execute(
        base.order_by(Notification.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()
    body = paginated([
        {
            "id": str(n.id),
            "kind": n.kind,
            "payload": n.payload_json,
            "created_at": n.created_at.isoformat(),
            "read_at": n.read_at.isoformat() if n.read_at else None,
        }
        for n in rows
    ], total, page, per_page)
    body["meta"]["unread"] = unread
    return body


@router.patch("/notifications/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, ctx: Auth, db: DB):
    notification = db.execute(
        select(Notification).where(Notification.id == notification_id)
    ).scalar_one_or_none()
    if notification is None:
        raise MedifyError("MDF-4041")
    if notification.read_at is None:
        notification.read_at = dt.datetime.now(dt.timezone.utc)
    return ok({"read": True})
