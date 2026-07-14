"""سجل التدقيق الإلحاقي — عمليات الأدمن وكل اعتماد/رفع (FR-303/NFR-10). لا محتوى سريرياً."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog


def audit(
    db: Session,
    facility_id: uuid.UUID,
    action: str,
    entity: str,
    entity_id: uuid.UUID | str | None = None,
    actor_user_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            facility_id=facility_id,
            actor_user_id=actor_user_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id else None,
            meta_json=meta,
            at=dt.datetime.now(dt.timezone.utc),
        )
    )
