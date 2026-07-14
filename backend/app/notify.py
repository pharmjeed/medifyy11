"""الإشعارات — حصراً أحداث DOC-12 الـ12. لا محتوى سريرياً في أي إشعار."""
from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Notification, User

# المفتاح: (القناة تشمل البريد؟، الأولوية)
NOTIFICATION_KINDS: dict[str, tuple[bool, str]] = {
    # الدكتور
    "dr.summary_ready": (False, "normal"),
    "dr.analysis_failed": (False, "important"),
    "dr.upload_success": (False, "normal"),
    "dr.upload_failed": (True, "critical"),
    "dr.safety_flag": (False, "critical"),
    "dr.password_reset": (False, "important"),
    # الأدمن
    "ad.upload_failed": (True, "critical"),
    "ad.integration_down": (True, "critical"),
    "ad.seats_exhausted": (False, "important"),
    "ad.payment_failed": (True, "critical"),
    "ad.renewal_upcoming": (True, "normal"),
    "ad.retention_purge": (False, "normal"),
}

assert len(NOTIFICATION_KINDS) == 12, "DOC-12: 12 حدثاً لا غير"


def _send_email_mock(to_email: str, kind: str, payload: dict[str, Any]) -> None:
    """EMAIL_ENGINE=mock (D-16): يكتب الرسالة إلى صندوق صادر محلي — بلا تفاصيل حساسة."""
    s = get_settings()
    outbox = Path(s.outbox_dir)
    outbox.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    (outbox / f"{stamp}-{kind}.json").write_text(
        json.dumps({"to": to_email, "kind": kind, "payload": payload}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def notify(
    db: Session,
    facility_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if kind not in NOTIFICATION_KINDS:
        raise ValueError(f"حدث خارج قائمة DOC-12: {kind}")
    email_channel, priority = NOTIFICATION_KINDS[kind]
    body = {"priority": priority, **(payload or {})}
    # Core INSERT بلا RETURNING — سياسة القراءة التقييدية (إشعاراتك فقط) تمنع RETURNING لمستخدم آخر
    from uuid6 import uuid7
    from sqlalchemy import insert
    db.execute(
        insert(Notification).values(
            id=uuid7(), facility_id=facility_id, user_id=user_id, kind=kind, payload_json=body
        )
    )
    if email_channel:
        user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if user is not None and user.email:
            _send_email_mock(user.email, kind, body)


def notify_admins(
    db: Session,
    facility_id: uuid.UUID,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> None:
    admins = db.execute(
        select(User).where(User.facility_id == facility_id, User.role == "admin", User.is_active == True)  # noqa: E712
    ).scalars().all()
    for admin in admins:
        notify(db, facility_id, admin.id, kind, payload)
