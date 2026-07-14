"""التتبع — حصراً أحداث DOC-14 الـ12. لا محتوى سريرياً ولا معرف مريض — أبداً (D-06)."""
from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from typing import Any

from .config import get_settings

logger = logging.getLogger("medify.analytics")

ANALYTICS_EVENTS = {
    "visit.started",
    "recording.completed",
    "summary.generated",
    "guidance.shown",
    "guidance.resolved",
    "edit.applied",
    "visit.approved",
    "upload.result",
    "template.reverse_built",
    "template.selected",
    "error.5xx",
    "session.daily_active",
}

assert len(ANALYTICS_EVENTS) == 12, "DOC-14: 12 حدثاً لا غير"

_FORBIDDEN_KEYS = {"patient_id", "display_name", "content", "text", "transcript", "summary", "mrn", "hospital_mrn"}


def track(
    event: str,
    facility_id: uuid.UUID | str,
    user_role: str,
    visit_id: uuid.UUID | str | None = None,
    **props: Any,
) -> None:
    if event not in ANALYTICS_EVENTS:
        raise ValueError(f"حدث خارج تصنيف DOC-14: {event}")
    for key in props:
        if key in _FORBIDDEN_KEYS:
            raise ValueError(f"خاصية محظورة في التحليلات (خصوصية DOC-14): {key}")
    record = {
        "event": event,
        "facility_id": str(facility_id),
        "user_role": user_role,
        "visit_id": str(visit_id) if visit_id else None,
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "app_version": get_settings().app_version,
        **props,
    }
    # ANALYTICS_ENGINE=log — مسجّل بنيوي؛ posthog self-hosted لاحقاً (D-06)
    logger.info(json.dumps(record, ensure_ascii=False, default=str))
