"""طابور المذكرات المعلّقة (م16) — «بانتظارك» بأربع مجموعات.

المجموعات (كل زيارة في واحدة فقط — الأولوية بالترتيب):
1. reopened_not_uploaded — نسخة جديدة قيد الإعداد بعد إعادة الفتح (الأثقل التزاماً)
2. awaiting_gate_two — البوابة ① أُنجزت وتنتظر اعتماد الأكواد
3. pending_guidance — إرشادات معلّقة تحجب البوابة ②
4. in_review — دخلت المراجعة ولم يُحسم فيها شيء بعد

الترتيب داخل كل مجموعة بالأقدم أولاً (العمر بالساعات من دخول in_review).
المُبطلة لا تظهر إطلاقاً. تقرير المدير الطبي أعداد فقط بلا محتوى.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Approval,
    AuditLog,
    GuidanceItem,
    NoteVersion,
    Patient,
    Summary,
    SummarySection,
    User,
    Visit,
)
from .visits import active_note_approval

GROUPS = ("reopened_not_uploaded", "awaiting_gate_two", "pending_guidance", "in_review")


def _entered_review_at(db: Session, visit: Visit) -> dt.datetime:
    """لحظة دخول in_review من سجل الانتقالات (م1) — وإلا إنشاء الزيارة."""
    row = db.execute(
        select(AuditLog.at)
        .where(
            AuditLog.action == "visit.state_changed",
            AuditLog.entity_id == str(visit.id),
            AuditLog.meta_json["to"].astext == "in_review",
        )
        .order_by(AuditLog.at.desc())
    ).scalars().first()
    return row or visit.created_at


def classify_visit(db: Session, visit: Visit) -> tuple[str, int]:
    """(المجموعة، عدد الإرشادات المعلّقة) — للزيارات في in_review حصراً."""
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    pending = 0
    if summary is not None:
        pending = db.execute(
            select(func.count(GuidanceItem.id))
            .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
            .where(SummarySection.summary_id == summary.id, GuidanceItem.status == "pending")
        ).scalar_one()

    has_uploaded_version = db.execute(
        select(func.count(NoteVersion.id)).where(
            NoteVersion.visit_id == visit.id, NoteVersion.upload_status == "uploaded")
    ).scalar_one() > 0
    if visit.cycle > 1 and has_uploaded_version:
        return "reopened_not_uploaded", pending
    if active_note_approval(db, visit) is not None:
        return "awaiting_gate_two", pending
    if pending > 0:
        return "pending_guidance", pending
    return "in_review", pending


def pending_for_doctor(db: Session, doctor_id: uuid.UUID, now: dt.datetime | None = None) -> dict[str, Any]:
    """طابور طبيبٍ بعينه — RLS يضمن أنه لا يرى غير زياراته."""
    now = now or dt.datetime.now(dt.timezone.utc)
    visits = db.execute(
        select(Visit).where(Visit.doctor_id == doctor_id, Visit.state == "in_review")
    ).scalars().all()

    groups: dict[str, list[dict[str, Any]]] = {name: [] for name in GROUPS}
    for visit in visits:
        group, pending = classify_visit(db, visit)
        entered = _entered_review_at(db, visit)
        patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one_or_none()
        groups[group].append({
            "visit_id": str(visit.id),
            "patient_name": patient.display_name if patient else "—",
            "patient_mrn": patient.hospital_mrn if patient else "—",
            "entered_review_at": entered.isoformat(),
            "age_hours": round((now - entered).total_seconds() / 3600, 1),
            "pending_guidance_count": pending,
            "version": visit.cycle,
        })
    for name in GROUPS:
        groups[name].sort(key=lambda row: row["entered_review_at"])  # الأقدم أولاً

    total = sum(len(rows) for rows in groups.values())
    return {
        "total": total,
        "groups": groups,
        "counts": {name: len(rows) for name, rows in groups.items()},
        "as_of": now.isoformat(),
    }


def send_daily_reminders(db: Session, now: dt.datetime | None = None) -> dict[str, Any]:
    """تذكير يومي (م16) — لكل طبيب لديه معلّق فقط (N>0)؛ صفر معلّق = لا إشعار."""
    from ..notify import notify

    now = now or dt.datetime.now(dt.timezone.utc)
    visits = db.execute(select(Visit).where(Visit.state == "in_review")).scalars().all()
    per_doctor: dict[tuple[uuid.UUID, uuid.UUID], list[dt.datetime]] = {}
    for visit in visits:
        per_doctor.setdefault((visit.facility_id, visit.doctor_id), []).append(
            _entered_review_at(db, visit))

    sent = 0
    for (facility_id, doctor_id), timestamps in per_doctor.items():
        if not timestamps:
            continue
        oldest_hours = round((now - min(timestamps)).total_seconds() / 3600, 1)
        notify(db, facility_id, doctor_id, "dr.summary_ready",
               {"reminder": "pending_queue", "pending_count": len(timestamps),
                "oldest_age_hours": oldest_hours})
        sent += 1
    db.flush()
    return {"reminders_sent": sent, "as_of": now.isoformat()}


def pending_report(db: Session, facility_id: uuid.UUID, now: dt.datetime | None = None) -> dict[str, Any]:
    """تقرير المدير الطبي — لكل طبيب: العدد ومتوسط العمر والأقدم. **أعداد فقط**."""
    now = now or dt.datetime.now(dt.timezone.utc)
    visits = db.execute(
        select(Visit).where(Visit.facility_id == facility_id, Visit.state == "in_review")
    ).scalars().all()
    doctors = {
        user.id: user.full_name
        for user in db.execute(select(User).where(User.facility_id == facility_id)).scalars()
    }

    by_doctor: dict[uuid.UUID, list[float]] = {}
    group_counts: dict[uuid.UUID, dict[str, int]] = {}
    for visit in visits:
        group, _pending = classify_visit(db, visit)
        entered = _entered_review_at(db, visit)
        age = (now - entered).total_seconds() / 3600
        by_doctor.setdefault(visit.doctor_id, []).append(age)
        counts = group_counts.setdefault(visit.doctor_id, {name: 0 for name in GROUPS})
        counts[group] += 1

    rows = []
    for doctor_id, ages in by_doctor.items():
        rows.append({
            "physician_id": str(doctor_id),
            "physician_name": doctors.get(doctor_id, "—"),
            "pending_count": len(ages),
            "avg_age_hours": round(sum(ages) / len(ages), 1),
            "oldest_age_hours": round(max(ages), 1),
            "by_group": group_counts.get(doctor_id, {}),
        })
    rows.sort(key=lambda row: row["oldest_age_hours"], reverse=True)
    return {"as_of": now.isoformat(), "physicians": rows,
            "total_pending": sum(row["pending_count"] for row in rows)}
