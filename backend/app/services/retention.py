"""سياسة الاحتفاظ الموحّدة (م8) — soft-delete ثم hard-delete بعد سماح 7 أيام.

الأنواع وافتراضاتها (retention_policies تجاوز لكل منشأة؛ NULL = بلا حذف):
audio=90 · transcript_raw=90 (يشمل diarization داخل نفس الصف) · intermediate_drafts=30
(edit_events كتابة/إملاء + processing_attempts) · ai_chat_logs=90 (edit_events قناة
ai_chat) · note_versions_uploaded=365 · audit_log=3650 · aggregated_metrics=بلا حذف.

قواعد حاكمة:
- visits.legal_hold يجمّد كل حذف لأثار الزيارة كلياً.
- الزيارات voided تتبع أقصر مدة مطبّقة (intermediate_drafts) لأنواعها الصوت/التفريغ.
- كل حذف يكتب Audit (نوع + عدد + نطاق — بلا محتوى إطلاقاً).
- الحذف الصلب للجداول الإلحاقية (audit_logs/note_versions) عبر صمام
  medify.retention='purge' الذي تضبطه هذه المهمة حصراً بدور المالك (0016).

تعمل بجلسة نظام (تتجاوز RLS) — مهمة دورية بلا فاعل بشري (actor_user_id=None).
الجدولة: arq cron ليلاً (worker) أو scripts/purge_recordings.py يدوياً.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    AuditLog,
    EditEvent,
    Facility,
    NoteVersion,
    ProcessingAttempt,
    Recording,
    RetentionPolicy,
    Transcript,
    Visit,
)
from ..notify import notify_admins

logger = logging.getLogger("medify.retention")

GRACE_DAYS = 7

# الافتراضات الملزمة (م8) — NULL = بلا حذف
DEFAULTS: dict[str, int | None] = {
    "audio": 90,
    "transcript_raw": 90,
    "intermediate_drafts": 30,
    "ai_chat_logs": 90,
    "note_versions_uploaded": 365,
    "audit_log": 3650,
    "aggregated_metrics": None,
}


def resolve_retention_days(db: Session, facility_id: uuid.UUID, artifact_type: str) -> int | None:
    """أيام الاحتفاظ الفعلية: تجاوز المنشأة إن وُجد وإلا الافتراض المضمّن."""
    row = db.execute(
        select(RetentionPolicy).where(
            RetentionPolicy.facility_id == facility_id,
            RetentionPolicy.artifact_type == artifact_type,
        )
    ).scalar_one_or_none()
    if row is not None:
        return row.retention_days
    return DEFAULTS.get(artifact_type)


def effective_policies(db: Session, facility_id: uuid.UUID) -> dict[str, int | None]:
    out = dict(DEFAULTS)
    rows = db.execute(
        select(RetentionPolicy).where(RetentionPolicy.facility_id == facility_id)
    ).scalars().all()
    for row in rows:
        if row.artifact_type in out:
            out[row.artifact_type] = row.retention_days
    return out


def _held_visit_ids(db: Session, facility_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.execute(
        select(Visit.id).where(Visit.facility_id == facility_id, Visit.legal_hold.is_(True))
    ).scalars())


def _voided_visit_ids(db: Session, facility_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.execute(
        select(Visit.id).where(Visit.facility_id == facility_id, Visit.state == "voided")
    ).scalars())


def _audit_purge(db: Session, facility_id: uuid.UUID, artifact_type: str,
                 stage: str, count: int, extra: dict | None = None) -> None:
    """سطر تدقيق مجمّع لكل نوع/مرحلة — نوع وعدد ونطاق، بلا محتوى (المبدأ 4/7)."""
    if count <= 0:
        return
    audit(db, facility_id, f"retention.{stage}", "retention", None, None,
          {"artifact_type": artifact_type, "count": count, **(extra or {})})


def sweep_retention(db: Session, now: dt.datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    """الكنس الليلي الموحّد — idempotent، لكل منشأة على حدة.

    soft: وسم المتقادم (deleted_at) · hard: إتلاف الموسوم منذ ≥ 7 أيام.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    grace = dt.timedelta(days=GRACE_DAYS)
    stats: dict[str, Any] = {"ran_at": now.isoformat(), "dry_run": dry_run, "facilities": {}}
    # صمام الحذف الإلحاقي (audit_logs/note_versions) — معاملة هذه الجلسة فقط
    if not dry_run:
        db.execute(text("SELECT set_config('medify.retention', 'purge', true)"))

    facility_ids = db.execute(select(Facility.id)).scalars().all()
    for facility_id in facility_ids:
        fstats: dict[str, int] = {}
        held = _held_visit_ids(db, facility_id)
        voided = _voided_visit_ids(db, facility_id)
        policies = effective_policies(db, facility_id)
        shortest = min((d for d in policies.values() if d is not None), default=30)

        def _expiry_cutoff(days: int | None, visit_id: uuid.UUID | None = None) -> dt.datetime | None:
            """المبطلة تتبع أقصر مدة — legal_hold يُستثنى قبل النداء."""
            if days is None:
                return None
            effective_days = shortest if (visit_id in voided) else days
            return now - dt.timedelta(days=effective_days)

        # ===== audio (recordings): soft بالوسم ثم hard بحذف الملف =====
        audio_days = policies["audio"]
        if audio_days is not None:
            candidates = db.execute(
                select(Recording).where(
                    Recording.facility_id == facility_id,
                    Recording.deleted_at.is_(None),
                )
            ).scalars().all()
            soft_count = 0
            for recording in candidates:
                if recording.visit_id in held:
                    continue
                # retention_until المختوم عند البدء هو الحاكم (السياسة تحكم الختم للجديد)؛
                # المُبطلة تتبع أقصر مدة مطبّقة أياً كان ختمها (م8)
                due = recording.retention_until
                if recording.visit_id in voided:
                    due = min(due, recording.created_at + dt.timedelta(days=shortest))
                if due <= now:
                    if not dry_run:
                        recording.deleted_at = now
                    soft_count += 1
            fstats["audio_soft"] = soft_count
            if not dry_run:
                _audit_purge(db, facility_id, "audio", "soft_deleted", soft_count)

            hard_due = db.execute(
                select(Recording).where(
                    Recording.facility_id == facility_id,
                    Recording.deleted_at.is_not(None),
                    Recording.deleted_at <= now - grace,
                )
            ).scalars().all()
            hard_count = 0
            for recording in hard_due:
                if recording.visit_id in held:
                    continue
                path = Path(recording.storage_uri)
                if not path.exists():
                    continue  # أُتلف سابقاً — لا إعادة تدوين (idempotent)
                if dry_run:
                    hard_count += 1
                    continue
                try:
                    path.unlink()
                    hard_count += 1
                    audit(db, facility_id, "recording.purged", "recording", recording.id, None,
                          {"file_was_present": True, "duration_sec": recording.duration_sec})
                except OSError as exc:
                    logger.error("تعذّر حذف تسجيل %s: %s", recording.id, exc)
            fstats["audio_hard"] = hard_count

        # ===== transcript_raw (+diarization داخل الصف): soft بالوسم ثم hard بحذف الصف =====
        tr_days = policies["transcript_raw"]
        if tr_days is not None:
            candidates = db.execute(
                select(Transcript).where(
                    Transcript.facility_id == facility_id,
                    Transcript.deleted_at.is_(None),
                )
            ).scalars().all()
            soft_count = 0
            for transcript in candidates:
                if transcript.visit_id in held:
                    continue
                cutoff = _expiry_cutoff(tr_days, transcript.visit_id)
                if cutoff is not None and transcript.created_at <= cutoff:
                    if not dry_run:
                        transcript.deleted_at = now
                    soft_count += 1
            fstats["transcript_soft"] = soft_count
            if not dry_run:
                _audit_purge(db, facility_id, "transcript_raw", "soft_deleted", soft_count)
                conditions = [
                    Transcript.facility_id == facility_id,
                    Transcript.deleted_at.is_not(None),
                    Transcript.deleted_at <= now - grace,
                ]
                if held:
                    conditions.append(Transcript.visit_id.not_in(held))
                hard = db.execute(delete(Transcript).where(and_(*conditions)))
                fstats["transcript_hard"] = hard.rowcount or 0
                _audit_purge(db, facility_id, "transcript_raw", "hard_deleted", fstats["transcript_hard"])

        # ===== edit_events: مسودات وسيطة (كتابة/إملاء 30ي) + محادثات AI (90ي) — صلب مباشر بعد السماح =====
        for artifact, channels in (("intermediate_drafts", ("typing", "voice")), ("ai_chat_logs", ("ai_chat",))):
            days = policies[artifact]
            if days is None or dry_run:
                continue
            cutoff = now - dt.timedelta(days=days) - grace
            conditions = [
                EditEvent.facility_id == facility_id,
                EditEvent.channel.in_(channels),
                EditEvent.created_at <= cutoff,
            ]
            if held:
                conditions.append(EditEvent.visit_id.not_in(held))
            result = db.execute(delete(EditEvent).where(and_(*conditions)))
            count = result.rowcount or 0
            fstats[artifact] = count
            _audit_purge(db, facility_id, artifact, "hard_deleted", count)

        # processing_attempts تتبع intermediate_drafts (تشغيلية بلا PHI)
        pa_days = policies["intermediate_drafts"]
        if pa_days is not None and not dry_run:
            cutoff = now - dt.timedelta(days=pa_days) - grace
            conditions = [
                ProcessingAttempt.facility_id == facility_id,
                ProcessingAttempt.created_at <= cutoff,
            ]
            if held:
                conditions.append(ProcessingAttempt.visit_id.not_in(held))
            result = db.execute(delete(ProcessingAttempt).where(and_(*conditions)))
            count = result.rowcount or 0
            fstats["processing_attempts"] = count
            _audit_purge(db, facility_id, "intermediate_drafts", "hard_deleted", count,
                         {"table": "processing_attempts"})

        # ===== note_versions المنقولة (365ي) — عبر صمام الاحتفاظ =====
        nv_days = policies["note_versions_uploaded"]
        if nv_days is not None and not dry_run:
            cutoff = now - dt.timedelta(days=nv_days) - grace
            conditions = [
                NoteVersion.facility_id == facility_id,
                NoteVersion.upload_status == "uploaded",
                NoteVersion.uploaded_at.is_not(None),
                NoteVersion.uploaded_at <= cutoff,
            ]
            if held:
                conditions.append(NoteVersion.visit_id.not_in(held))
            result = db.execute(delete(NoteVersion).where(and_(*conditions)))
            count = result.rowcount or 0
            fstats["note_versions"] = count
            _audit_purge(db, facility_id, "note_versions_uploaded", "hard_deleted", count)

        # ===== audit_log (3650ي) — آخر ما يُكنس، عبر الصمام كذلك =====
        al_days = policies["audit_log"]
        if al_days is not None and not dry_run:
            cutoff = now - dt.timedelta(days=al_days) - grace
            result = db.execute(
                delete(AuditLog).where(
                    AuditLog.facility_id == facility_id,
                    AuditLog.at <= cutoff,
                )
            )
            count = result.rowcount or 0
            fstats["audit_log"] = count
            _audit_purge(db, facility_id, "audit_log", "hard_deleted", count)

        total = sum(fstats.values())
        if total and not dry_run:
            notify_admins(db, facility_id, "ad.retention_purge", {"purged": total})
        if total:
            stats["facilities"][str(facility_id)] = fstats

    if not dry_run:
        db.flush()
    logger.info("سياسة الاحتفاظ الموحّدة: %s", stats)
    return stats


def retention_status(db: Session, facility_id: uuid.UUID,
                     now: dt.datetime | None = None) -> dict[str, Any]:
    """GET /admin/retention-status — ما سيُحذف خلال 7 أيام + الموسوم بانتظار الصلب. أعداد فقط."""
    now = now or dt.datetime.now(dt.timezone.utc)
    week = dt.timedelta(days=GRACE_DAYS)
    held = _held_visit_ids(db, facility_id)
    policies = effective_policies(db, facility_id)
    out: dict[str, Any] = {"policies": policies, "grace_days": GRACE_DAYS, "as_of": now.isoformat()}

    def _count(query) -> int:
        return db.execute(query).scalar_one()

    audio_days = policies["audio"]
    audio: dict[str, int] = {"due_within_7d": 0, "awaiting_hard": 0}
    if audio_days is not None:
        cutoff_soon = now + week - dt.timedelta(days=audio_days)
        conditions = [Recording.facility_id == facility_id, Recording.deleted_at.is_(None),
                      Recording.created_at <= cutoff_soon]
        if held:
            conditions.append(Recording.visit_id.not_in(held))
        audio["due_within_7d"] = _count(select(func.count(Recording.id)).where(and_(*conditions)))
        audio["awaiting_hard"] = _count(select(func.count(Recording.id)).where(
            Recording.facility_id == facility_id, Recording.deleted_at.is_not(None)))
    out["audio"] = audio

    tr_days = policies["transcript_raw"]
    transcript: dict[str, int] = {"due_within_7d": 0, "awaiting_hard": 0}
    if tr_days is not None:
        cutoff_soon = now + week - dt.timedelta(days=tr_days)
        conditions = [Transcript.facility_id == facility_id, Transcript.deleted_at.is_(None),
                      Transcript.created_at <= cutoff_soon]
        if held:
            conditions.append(Transcript.visit_id.not_in(held))
        transcript["due_within_7d"] = _count(select(func.count(Transcript.id)).where(and_(*conditions)))
        transcript["awaiting_hard"] = _count(select(func.count(Transcript.id)).where(
            Transcript.facility_id == facility_id, Transcript.deleted_at.is_not(None)))
    out["transcript_raw"] = transcript

    out["legal_hold_visits"] = len(held)
    return out


def purge_expired_recordings(db: Session, now: dt.datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    """توافق خلفي (scripts/purge_recordings.py) — يستدعي الكنس الموحّد ويعيد مفاتيح قريبة."""
    stats = sweep_retention(db, now=now, dry_run=dry_run)
    purged = sum(f.get("audio_soft", 0) + f.get("audio_hard", 0) for f in stats["facilities"].values())
    return {"purged": purged, "dry_run": dry_run, "ran_at": stats["ran_at"], "details": stats}
