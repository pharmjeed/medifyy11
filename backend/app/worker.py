"""عامل arq — معالجة P1→P3 خارج دورة الطلب (المرحلة 3 من التحصين).

التشغيل: `arq app.worker.WorkerSettings` (خدمة worker في docker-compose).
recording/stop يثبّت الحالة transcribed ثم يُدرج المهمة؛ العامل يجري المراحل
بمحاولاتها المصنّفة (services/processing) بجلسة RLS للمنشأة نفسها. الفشل النهائي
يبقي الزيارة transcribed — الواجهة تعرضه من processing-status وتعيد عبر /reprocess.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from .config import get_settings
from .db import rls_session, system_session
from .models import Visit
from .services.processing import process_visit_pipeline

logger = logging.getLogger("medify.worker")


def _process_sync(visit_id: str) -> None:
    with system_session() as sdb:
        row = sdb.execute(
            select(Visit.facility_id, Visit.doctor_id, Visit.state).where(Visit.id == uuid.UUID(visit_id))
        ).one_or_none()
    if row is None:
        logger.warning("مهمة معالجة لزيارة غير موجودة %s", visit_id)
        return
    if row.state != "transcribed":
        logger.info("زيارة %s في %s — لا معالجة (idempotent)", visit_id, row.state)
        return
    with rls_session(row.facility_id, row.doctor_id, "doctor") as db:
        visit = db.execute(select(Visit).where(Visit.id == uuid.UUID(visit_id))).scalar_one()
        process_visit_pipeline(db, visit, actor_user_id=None)


async def process_visit(ctx: dict, visit_id: str) -> None:
    """مهمة arq — التنفيذ المتزامن (DB/محركات) في thread كي لا يُحجب حدث العامل."""
    await asyncio.to_thread(_process_sync, visit_id)


def _retention_sync() -> None:
    from .services.retention import sweep_retention

    with system_session() as db:
        sweep_retention(db)


async def retention_nightly(ctx: dict) -> None:
    """المهمة الليلية (م8): soft-delete ثم hard-delete بعد سماح 7 أيام — Audit لكل حذف."""
    await asyncio.to_thread(_retention_sync)


def _redis_settings():
    from arq.connections import RedisSettings

    url = get_settings().redis_url
    if not url:
        raise RuntimeError("REDIS_URL مطلوب لتشغيل عامل المعالجة (queue mode)")
    return RedisSettings.from_dsn(url)


def _metrics_sync() -> None:
    from .services.metrics import aggregate_daily_metrics

    with system_session() as db:
        aggregate_daily_metrics(db)


async def metrics_nightly(ctx: dict) -> None:
    """التجميع الليلي (م15): أحداث الأمس → daily_metrics الذي تقرأ منه اللوحات."""
    await asyncio.to_thread(_metrics_sync)


def _reminders_sync() -> None:
    from .services.pending_queue import send_daily_reminders

    with system_session() as db:
        send_daily_reminders(db)


async def pending_reminders_daily(ctx: dict) -> None:
    """تذكير «بانتظارك» اليومي (م16) — للأطباء ذوي المعلّق فقط."""
    await asyncio.to_thread(_reminders_sync)


def _cron_jobs():
    from arq import cron

    # 02:30 الكنس الاحتفاظي (م8) · 03:00 تجميع المقاييس (م15) · تذكير الطابور (م16)
    return [
        cron(retention_nightly, hour=2, minute=30),
        cron(metrics_nightly, hour=3, minute=0),
        cron(pending_reminders_daily, hour=get_settings().pending_reminder_hour, minute=0),
    ]


class WorkerSettings:
    functions = [process_visit]
    cron_jobs = _cron_jobs()
    redis_settings = _redis_settings()  # يُقيَّم عند استيراد وحدة العامل (بيئة العامل فقط)
    job_timeout = 1800  # استشارة طويلة + إعادات 30/120/300 — سقف نصف ساعة
    max_tries = 1  # الإعادات داخل process_visit_pipeline لا عبر arq (سجل موحّد)
    keep_result = 3600
