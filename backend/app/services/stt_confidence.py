"""عتبات ثقة التفريغ (م11) — قابلة للضبط من كونسول المالك بلا deploy.

المفتاح: platform_settings['stt.confidence_thresholds'] = {"low": .., "medium": ..}
النمط نفسه المعتمد في ai_models (D-33): جلسة نظام + سقوط آمن للافتراضات عند أي عطل.
تُقرأ عند كل طلب عرض — تغيير القيمة يسري فوراً (معيار قبول م11).
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from ..db import system_session
from ..models import PlatformSetting

logger = logging.getLogger("medify.stt_confidence")

SETTING_KEY = "stt.confidence_thresholds"
DEFAULT_THRESHOLDS = {"low": 0.55, "medium": 0.75}


def resolve_thresholds() -> dict[str, float]:
    try:
        with system_session() as db:
            row = db.execute(
                select(PlatformSetting).where(PlatformSetting.key == SETTING_KEY)
            ).scalar_one_or_none()
            if row is not None and isinstance(row.value, dict):
                low = float(row.value.get("low", DEFAULT_THRESHOLDS["low"]))
                medium = float(row.value.get("medium", DEFAULT_THRESHOLDS["medium"]))
                if 0.0 < low <= medium <= 1.0:
                    return {"low": low, "medium": medium}
    except Exception as exc:  # جدول غير مهاجر/قاعدة متعذرة — لا توقف (D-03)
        logger.warning("تعذّر قراءة عتبات الثقة (%s) — الافتراضات", exc)
    return dict(DEFAULT_THRESHOLDS)


def set_thresholds(db, low: float, medium: float, admin_id) -> dict[str, float]:
    """كتابة عتبات المنصة — تُستدعى من كونسول المالك (جلسة نظام)."""
    row = db.execute(
        select(PlatformSetting).where(PlatformSetting.key == SETTING_KEY)
    ).scalar_one_or_none()
    value = {"low": low, "medium": medium}
    if row is None:
        row = PlatformSetting(key=SETTING_KEY, value=value, updated_by=admin_id)
        db.add(row)
    else:
        row.value = value
        row.updated_by = admin_id
    db.flush()
    return value
