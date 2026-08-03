"""تشغيل P1→P2→P3 بمحاولات مصنّفة وسجل معمَّر (المرحلة 3 من التحصين).

وضعان يحكمهما PROCESSING_MODE (والافتراضي آلي حسب REDIS_URL):
- inline: داخل الطلب (dev/الاختبارات — بلا Redis) كما كان قبل التحصين.
- queue: عامل arq مستقل (النشر) — recording/stop يعيد فوراً والواجهة تستطلع
  processing-status؛ لا حجز طلب HTTP ولا معاملة قاعدة مفتوحة لدقائق.

المحاولات: العابر (timeout/اتصال/5xx/rate-limit) يعاد بتباعد 30ث/2د/5د (قابل للضبط
بـ PROCESSING_RETRY_DELAYS) ثم MDF نهائي بإشعار؛ الثابت (ملف تالف/صيغة/صوت فارغ)
يفشل فوراً بمحاولة واحدة. كل محاولة صف في processing_attempts يُكتب بجلسة نظام
مستقلة — ينجو من rollback الطلب الفاشل. فشل P3 يبقى غير معطِّل (ملخص بلا إرشادات).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
import uuid
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics import track
from ..config import get_settings
from ..db import system_session
from ..errors import MedifyError
from ..models import GuidanceItem, ProcessingAttempt, Summary, SummarySection, Transcript, Visit
from ..notify import notify
from ..pipelines.classify import NON_RETRYABLE, classify_error
from ..pipelines.run import run_guidance, run_summary, run_transcription
from .visits import transition

logger = logging.getLogger("medify.processing")

STAGE_FINAL_MDF = {"P1": "MDF-5031", "P2": "MDF-5032", "P3": "MDF-5033"}


def retry_delays() -> list[float]:
    """تباعد الإعادات بالثواني — "30,120,300" افتراضاً (الاختبارات تصفّرها)."""
    raw = get_settings().processing_retry_delays
    try:
        return [max(0.0, float(part)) for part in raw.split(",") if part.strip() != ""]
    except ValueError:
        return [30.0, 120.0, 300.0]


def attempts_total() -> int:
    return 1 + len(retry_delays())


def queue_mode_enabled() -> bool:
    s = get_settings()
    if s.processing_mode == "inline":
        return False
    if s.processing_mode == "queue":
        return True
    return bool(s.redis_url)


def _log_attempt(visit: Visit, stage: str, attempt_no: int, error_class: str,
                 error_detail: str | None, started_at: dt.datetime, succeeded: bool) -> None:
    """جلسة نظام مستقلة — صف المحاولة يبقى حتى لو انتهى الطلب بـ rollback."""
    try:
        with system_session() as sdb:
            sdb.add(ProcessingAttempt(
                visit_id=visit.id,
                facility_id=visit.facility_id,
                stage=stage,
                attempt_no=attempt_no,
                error_class=error_class,
                error_detail=error_detail,
                succeeded=succeeded,
                started_at=started_at,
                finished_at=dt.datetime.now(dt.timezone.utc),
            ))
    except Exception:  # سجل المحاولات لا يُسقط المعالجة نفسها أبداً
        logger.exception("تعذّر تدوين محاولة %s للزيارة %s", stage, visit.id)


def _notify_final_failure(visit: Visit, mdf_code: str) -> None:
    """إخطار الفشل النهائي بجلسة نظام — ينجو من rollback الطلب (MDF-5031/5032)."""
    try:
        with system_session() as sdb:
            notify(sdb, visit.facility_id, visit.doctor_id, "dr.analysis_failed",
                   {"visit_id": str(visit.id), "mdf": mdf_code})
    except Exception:
        logger.exception("تعذّر إخطار فشل المعالجة للزيارة %s", visit.id)


def _run_stage(visit: Visit, stage: str, fn: Callable[[], object]) -> object:
    """محاولة أولى + إعادات على العابر فقط — يرفع آخر استثناء بعد الاستنفاد."""
    delays = retry_delays()
    total = 1 + len(delays)
    for attempt_no in range(1, total + 1):
        started_at = dt.datetime.now(dt.timezone.utc)
        try:
            result = fn()
        except MedifyError:
            raise  # خطأ مُصنَّف مسبقاً من طبقة أدنى — لا يُغلَّف ولا يُعاد
        except Exception as exc:
            error_class = classify_error(exc)
            detail = f"{exc.__class__.__name__}: {str(exc)[:400]}"  # بلا PHI — رسائل محركات تقنية
            _log_attempt(visit, stage, attempt_no, error_class, detail, started_at, succeeded=False)
            if error_class == NON_RETRYABLE or attempt_no == total:
                logger.error("%s فشل نهائياً للزيارة %s (محاولة %d/%d، %s)",
                             stage, visit.id, attempt_no, total, error_class)
                raise
            delay = delays[attempt_no - 1]
            logger.warning("%s — محاولة %d/%d فشلت (%s) — إعادة بعد %.0f ثانية",
                           stage, attempt_no, total, exc, delay)
            if delay > 0:
                time.sleep(delay)
            continue
        _log_attempt(visit, stage, attempt_no, "none", None, started_at, succeeded=True)
        return result
    raise RuntimeError("unreachable")  # الحلقة ترفع أو تعيد دائماً


def process_visit_pipeline(db: Session, visit: Visit, actor_user_id: uuid.UUID | None = None) -> bool:
    """P1→P2→P3 بتخطي المراحل المكتملة (idempotent) — يعيد guidance_ok.

    يُستدعى inline من recording/stop أو من عامل arq — التقدم الحالتي (summarized/
    in_review) عبر transition الموحّد بخطاف Audit (المرحلة 1).
    """
    transcript = db.execute(select(Transcript).where(Transcript.visit_id == visit.id)).scalar_one_or_none()
    if transcript is None:
        try:
            _run_stage(visit, "P1", lambda: run_transcription(db, visit))
        except MedifyError:
            raise
        except Exception as exc:
            _notify_final_failure(visit, "MDF-5031")
            raise MedifyError("MDF-5031", details={"visit_id": str(visit.id)}) from exc

    # م9: أرشفة FLAC بعد نجاح P1 — غير معطِّلة (فشلها يبقي WAV كما هو حرفياً)
    if get_settings().flac_archive != "off":
        try:
            from .audio_archive import archive_recording_to_flac

            archive_recording_to_flac(db, visit)
        except Exception:
            logger.exception("أرشفة FLAC تعذّرت للزيارة %s — الأصل باقٍ", visit.id)

    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    if summary is None:
        try:
            summary = _run_stage(visit, "P2", lambda: run_summary(db, visit))
        except MedifyError:
            raise
        except Exception as exc:
            _notify_final_failure(visit, "MDF-5032")
            raise MedifyError("MDF-5032", details={"visit_id": str(visit.id)}) from exc

    if visit.state == "transcribed":
        transition(db, visit, "summarized", actor_user_id)

    existing_guidance = db.execute(
        select(func.count(GuidanceItem.id))
        .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
        .where(SummarySection.summary_id == summary.id)
    ).scalar_one()
    guidance_ok = True
    if existing_guidance == 0:
        try:
            _run_stage(visit, "P3", lambda: run_guidance(db, visit, summary))
        except Exception as exc:
            # فشل P3 غير معطِّل (W-224): ملخص بلا إرشادات + إخطار MDF-5033
            logger.error("P3 فشل للزيارة %s: %s", visit.id, exc)
            notify(db, visit.facility_id, visit.doctor_id, "dr.analysis_failed",
                   {"visit_id": str(visit.id), "mdf": "MDF-5033"})
            track("error.5xx", visit.facility_id, "doctor", visit.id, mdf_code="MDF-5033", pipeline_id="P3")
            guidance_ok = False

    if visit.state == "summarized":
        transition(db, visit, "in_review", actor_user_id)
    return guidance_ok


def enqueue_process_visit(visit_id: uuid.UUID | str) -> None:
    """إدراج مهمة المعالجة في arq — _job_id يجعل التكرار idempotent (stop مزدوج = مهمة واحدة)."""
    from arq.connections import RedisSettings, create_pool

    async def _enqueue() -> None:
        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            await pool.enqueue_job("process_visit", str(visit_id), _job_id=f"process:{visit_id}")
        finally:
            await pool.close()

    asyncio.run(_enqueue())
