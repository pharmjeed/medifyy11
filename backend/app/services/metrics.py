"""القياس الآلي (م15) — أحداث بأرقام فقط + تجميع ليلي.

المقاييس:
- edit_distance: Levenshtein على مستوى الكلمات بين مسودة P2 والنص المعتمد،
  منسّبة 0–1، إجمالية ولكل قسم SOAP. الـdiff يُحسب بالذاكرة ويُرمى — الدرجة فقط تُخزَّن.
- الأزمنة: إنهاء التسجيل → الاعتماد النهائي · وقت شاشة المراجعة.
- نسب P3: accepted/rejected/modified.
- reopen_rate · claim_readiness_first_pass.

قاعدة حاكمة: numeric_payload أرقام حصراً — أي قيمة غير رقمية تُرفض (يُفرض تطبيقياً
ويُختبر آلياً)، فلا يتسرب محتوى سريري إلى طبقة القياس.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Approval,
    Clinic,
    DailyMetric,
    GuidanceItem,
    MetricEvent,
    Recording,
    Summary,
    SummarySection,
    User,
    Visit,
)

logger = logging.getLogger("medify.metrics")

EVENT_TYPES = (
    "visit.edit_distance",
    "visit.turnaround",
    "visit.guidance_rates",
    "visit.reopened",
    "visit.claim_readiness",
)


def _assert_numeric(payload: dict[str, Any]) -> dict[str, float]:
    """أرقام حصراً — bool مرفوض أيضاً (يُخزَّن 0/1 صريحاً عند الحاجة)."""
    clean: dict[str, float] = {}
    for key, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"numeric_payload يقبل الأرقام فقط — المفتاح {key} من نوع {type(value).__name__}")
        clean[key] = float(value)
    return clean


def record_metric(db: Session, visit: Visit, event_type: str, payload: dict[str, Any]) -> None:
    """تدوين حدث قياس — لا يُسقط المسار الرئيسي أبداً عند أي عطل."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"حدث قياس غير معرّف: {event_type}")
    try:
        numeric = _assert_numeric(payload)
        doctor = db.execute(select(User).where(User.id == visit.doctor_id)).scalar_one_or_none()
        db.add(MetricEvent(
            facility_id=visit.facility_id,
            event_type=event_type,
            visit_id=visit.id,
            physician_id=visit.doctor_id,
            specialty=(doctor.specialty if doctor is not None else None),
            clinic_id=visit.clinic_id,
            numeric_payload=numeric,
        ))
        db.flush()
    except Exception:
        logger.exception("تعذّر تدوين حدث القياس %s للزيارة %s", event_type, visit.id)


# ===== edit_distance =====

def word_levenshtein(source: str, target: str) -> int:
    """مسافة تحرير على مستوى الكلمات (سطرا DP — الذاكرة O(n))."""
    a = source.split()
    b = target.split()
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, word_a in enumerate(a, start=1):
        current = [i]
        for j, word_b in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,            # حذف
                current[j - 1] + 1,         # إضافة
                previous[j - 1] + (word_a != word_b),  # استبدال
            ))
        previous = current
    return previous[-1]


def normalized_edit_distance(original: str, current: str) -> float:
    """0 = لم يُمس · 1 = أُعيدت كتابته كلياً — منسّبة بأطول النصين (كلمات)."""
    denominator = max(len(original.split()), len(current.split()))
    if denominator == 0:
        return 0.0
    return round(min(1.0, word_levenshtein(original, current) / denominator), 4)


def compute_edit_distance(db: Session, visit: Visit) -> dict[str, float]:
    """الدرجة الإجمالية + لكل قسم — الـdiff نفسه لا يُخزَّن (المبدأ 7)."""
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    if summary is None:
        return {}
    sections = db.execute(
        select(SummarySection).where(SummarySection.summary_id == summary.id)
        .order_by(SummarySection.position)
    ).scalars().all()
    payload: dict[str, float] = {}
    total_distance = 0
    total_words = 0
    for section in sections:
        original = section.content_original or ""
        current = section.content_current or ""
        payload[f"section_{section.section_key}"] = normalized_edit_distance(original, current)
        total_distance += word_levenshtein(original, current)
        total_words += max(len(original.split()), len(current.split()))
    payload["overall"] = round(min(1.0, total_distance / total_words), 4) if total_words else 0.0
    return payload


def compute_guidance_rates(db: Session, visit: Visit) -> dict[str, float]:
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    if summary is None:
        return {}
    rows = db.execute(
        select(GuidanceItem.status, func.count(GuidanceItem.id))
        .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
        .where(SummarySection.summary_id == summary.id)
        .group_by(GuidanceItem.status)
    ).all()
    counts = {status: count for status, count in rows}
    total = sum(counts.values())
    if not total:
        return {}
    return {
        "total": float(total),
        "accepted_rate": round(counts.get("accepted", 0) / total, 4),
        "rejected_rate": round(counts.get("rejected", 0) / total, 4),
        "modified_rate": round(counts.get("modified", 0) / total, 4),
    }


def record_approval_metrics(db: Session, visit: Visit, *, review_ms: int,
                            claim_readiness_first_pass: bool) -> None:
    """تُستدعى عند البوابة ② — كل مقاييس الزيارة دفعةً واحدة."""
    edit_scores = compute_edit_distance(db, visit)
    if edit_scores:
        record_metric(db, visit, "visit.edit_distance", edit_scores)

    rates = compute_guidance_rates(db, visit)
    if rates:
        record_metric(db, visit, "visit.guidance_rates", rates)

    recording = db.execute(select(Recording).where(Recording.visit_id == visit.id)).scalar_one_or_none()
    approval = db.execute(
        select(Approval).where(Approval.visit_id == visit.id, Approval.cycle == visit.cycle)
    ).scalar_one_or_none()
    payload = {"review_ms": float(review_ms)}
    if recording is not None and approval is not None:
        payload["stop_to_final_approval_ms"] = float(
            (approval.approved_at - recording.created_at).total_seconds() * 1000)
    record_metric(db, visit, "visit.turnaround", payload)

    record_metric(db, visit, "visit.claim_readiness",
                  {"first_pass": 1.0 if claim_readiness_first_pass else 0.0})


def record_reopen(db: Session, visit: Visit, new_version: int) -> None:
    record_metric(db, visit, "visit.reopened", {"version": float(new_version)})


# ===== التجميع الليلي =====

def _dimension_keys(event: MetricEvent) -> list[tuple[str, str]]:
    keys = [("facility", str(event.facility_id))]
    if event.physician_id:
        keys.append(("physician", str(event.physician_id)))
    if event.specialty:
        keys.append(("specialty", event.specialty))
    if event.clinic_id:
        keys.append(("clinic", str(event.clinic_id)))
    return keys


def aggregate_daily_metrics(db: Session, day: dt.date | None = None) -> dict[str, Any]:
    """تجميع أحداث يومٍ في daily_metrics — idempotent (يُعيد كتابة شرائح اليوم)."""
    day = day or (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1))
    start = dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    events = db.execute(
        select(MetricEvent).where(MetricEvent.created_at >= start, MetricEvent.created_at < end)
    ).scalars().all()

    buckets: dict[tuple, list[float]] = {}
    for event in events:
        for dimension, key in _dimension_keys(event):
            for metric_key, value in (event.numeric_payload or {}).items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                slice_key = (event.facility_id, dimension, key, f"{event.event_type}.{metric_key}")
                buckets.setdefault(slice_key, []).append(float(value))

    written = 0
    for (facility_id, dimension, key, metric), values in buckets.items():
        row = db.execute(
            select(DailyMetric).where(
                DailyMetric.facility_id == facility_id,
                DailyMetric.day == day,
                DailyMetric.dimension == dimension,
                DailyMetric.dimension_key == key,
                DailyMetric.metric == metric,
            )
        ).scalar_one_or_none()
        if row is None:
            row = DailyMetric(facility_id=facility_id, day=day, dimension=dimension,
                              dimension_key=key, metric=metric)
            db.add(row)
        row.samples = len(values)
        row.total = round(sum(values), 6)
        row.average = round(sum(values) / len(values), 6)
        written += 1
    db.flush()
    result = {"day": day.isoformat(), "events": len(events), "slices": written}
    logger.info("تجميع المقاييس اليومي: %s", result)
    return result


def metrics_summary(db: Session, facility_id: uuid.UUID, date_from: dt.date, date_to: dt.date,
                    group_by: str = "facility") -> dict[str, Any]:
    """قراءة اللوحات من المجمَّع حصراً — أرقام فقط."""
    if group_by not in ("facility", "physician", "specialty", "clinic"):
        group_by = "facility"
    rows = db.execute(
        select(DailyMetric).where(
            DailyMetric.facility_id == facility_id,
            DailyMetric.dimension == group_by,
            DailyMetric.day >= date_from,
            DailyMetric.day <= date_to,
        )
    ).scalars().all()

    grouped: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        entry = grouped.setdefault(row.dimension_key, {})
        metric = entry.setdefault(row.metric, {"samples": 0.0, "total": 0.0})
        metric["samples"] += row.samples
        metric["total"] += row.total
    out: dict[str, Any] = {}
    for key, metrics in grouped.items():
        out[key] = {
            metric: {
                "samples": int(values["samples"]),
                "average": round(values["total"] / values["samples"], 4) if values["samples"] else 0.0,
            }
            for metric, values in metrics.items()
        }

    labels: dict[str, str] = {}
    if group_by == "physician":
        for user in db.execute(select(User).where(User.facility_id == facility_id)).scalars():
            labels[str(user.id)] = user.full_name
    elif group_by == "clinic":
        for clinic in db.execute(select(Clinic).where(Clinic.facility_id == facility_id)).scalars():
            labels[str(clinic.id)] = clinic.name

    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "group_by": group_by,
        "labels": labels,
        "groups": out,
    }
