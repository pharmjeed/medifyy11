"""تنفيذ سياسة الاحتفاظ بالصوت (A4 — توجيه المالك 2026-07-22).

الأعمدة كانت موجودة (`recordings.retention_until` / `deleted_at`) بلا منفّذ.
هنا المنفّذ: يحذف ملف الصوت فعلياً، يختم `deleted_at`، ويكتب حدث تدقيق لكل عملية حذف.

يعمل بجلسة نظام (تتجاوز RLS) لأنه مهمة دورية خارج دورة الطلب ولا فاعل بشري لها —
ولذلك `actor_user_id=None` في سجل التدقيق، تماماً كأفعال المنصة.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import Recording
from ..notify import notify_admins

logger = logging.getLogger("medify.retention")


def purge_expired_recordings(db: Session, now: dt.datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    """يحذف تسجيلات انقضت مدة احتفاظها. idempotent — المحذوف سابقاً يُتجاوز."""
    now = now or dt.datetime.now(dt.timezone.utc)
    due = db.execute(
        select(Recording).where(
            Recording.retention_until <= now,
            Recording.deleted_at.is_(None),
        ).order_by(Recording.retention_until)
    ).scalars().all()

    purged = 0
    missing = 0
    failed = 0
    by_facility: dict[uuid.UUID, int] = {}

    for recording in due:
        path = Path(recording.storage_uri)
        was_present = path.exists()
        if dry_run:
            purged += 1
            continue
        try:
            if was_present:
                path.unlink()
            else:
                missing += 1  # الملف غائب أصلاً — نختم الحذف كي لا يُعاد فحصه
        except OSError as exc:
            failed += 1
            logger.error("تعذّر حذف تسجيل %s: %s", recording.id, exc)
            continue

        recording.deleted_at = now
        by_facility[recording.facility_id] = by_facility.get(recording.facility_id, 0) + 1
        # حدث تدقيق لكل عملية حذف — بلا فاعل بشري (مهمة دورية)
        audit(
            db, recording.facility_id, "recording.purged", "recording", recording.id, None,
            {
                "retention_until": recording.retention_until.isoformat(),
                "file_was_present": was_present,
                "duration_sec": recording.duration_sec,
            },
        )
        purged += 1

    if not dry_run:
        db.flush()
        for facility_id, count in by_facility.items():
            notify_admins(db, facility_id, "ad.retention_purge", {"purged": count})
        db.flush()

    result = {
        "checked": len(due),
        "purged": purged,
        "files_already_missing": missing,
        "failed": failed,
        "facilities": len(by_facility),
        "dry_run": dry_run,
        "ran_at": now.isoformat(),
    }
    logger.info("سياسة الاحتفاظ: %s", result)
    return result
