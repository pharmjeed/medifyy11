"""ملف المريض داخل ميديفاي — المراجعات السابقة وما اعتُمد فيها (تعديل مالك 2026-07-26).

مصدر واحد للقطة السياق: بدل نص ثابت يُقدَّم لكل مريض، تُبنى اللقطة من زيارات المريض
السابقة الفعلية (تواريخها وقوالبها وخلاصاتها وتشخيصاتها وأدويتها المعتمدة). ما يخرج من
هنا يُعرض للطبيب ويُغذّي الإرشاد (P3) — فلا يدخله إلا ما وثّقه طبيب واعتمده.

RLS يحصر المحتوى السريري بزيارات الطبيب نفسه؛ الفلترة بـ`doctor_id` تجعل الحصر صريحاً.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GuidanceItem, Summary, SummarySection, Template, Visit

# حالات تعني أن الزيارة أنتجت مذكرة يمكن الاستناد إليها — المسودة والملغاة cancelled
# والمبطلة voided (مريض خطأ/مكررة/تجريبية — قرار مالك 2026-08-03) لا تُحسب مراجعة
HISTORY_STATES = ("summarized", "in_review", "approved", "uploaded", "upload_failed")
HISTORY_LIMIT = 5              # آخر خمس مراجعات — يكفي للاستمرارية ويُبقي المطالبة رشيقة
DIGEST_CHARS = 600             # سقف خلاصة المذكرة الواحدة داخل اللقطة
RESOLVED = ("accepted", "modified")   # المعتمد حصراً — المعلق والمرفوض ليسا من ملف المريض


def _digest(sections: list[SummarySection]) -> str:
    """خلاصة مضغوطة للمذكرة: «المفتاح: المحتوى» بترتيب القالب، مقصوصة عند السقف."""
    parts = [f"{section.section_key}: {(section.content_current or '').strip()}" for section in sections]
    text = " · ".join(part for part in parts if not part.endswith(": "))
    return text[:DIGEST_CHARS]


def previous_visits(
    db: Session,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    exclude_visit_id: uuid.UUID | None = None,
    limit: int = HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    """المراجعات السابقة للمريض — الأحدث أولاً. قائمة فارغة = أول مراجعة عند هذا الطبيب."""
    conditions = [
        Visit.patient_id == patient_id,
        Visit.doctor_id == doctor_id,
        Visit.state.in_(HISTORY_STATES),
    ]
    if exclude_visit_id is not None:
        conditions.append(Visit.id != exclude_visit_id)
    visits = db.execute(
        select(Visit).where(*conditions).order_by(Visit.created_at.desc()).limit(limit)
    ).scalars().all()
    if not visits:
        return []

    visit_ids = [visit.id for visit in visits]
    template_names = {
        template.id: template.name
        for template in db.execute(
            select(Template).where(Template.id.in_({visit.template_id for visit in visits}))
        ).scalars()
    }
    summaries = {
        summary.visit_id: summary
        for summary in db.execute(select(Summary).where(Summary.visit_id.in_(visit_ids))).scalars()
    }
    sections_by_summary: dict[uuid.UUID, list[SummarySection]] = {}
    if summaries:
        rows = db.execute(
            select(SummarySection)
            .where(SummarySection.summary_id.in_({summary.id for summary in summaries.values()}))
            .order_by(SummarySection.position)
        ).scalars().all()
        for section in rows:
            sections_by_summary.setdefault(section.summary_id, []).append(section)

    section_ids = {section.id for sections in sections_by_summary.values() for section in sections}
    items_by_section: dict[uuid.UUID, list[GuidanceItem]] = {}
    if section_ids:
        for item in db.execute(
            select(GuidanceItem).where(GuidanceItem.section_id.in_(section_ids))
        ).scalars():
            items_by_section.setdefault(item.section_id, []).append(item)

    out: list[dict[str, Any]] = []
    for visit in visits:
        summary = summaries.get(visit.id)
        sections = sections_by_summary.get(summary.id, []) if summary is not None else []
        resolved = [
            item
            for section in sections
            for item in items_by_section.get(section.id, [])
            if item.status in RESOLVED
        ]
        out.append({
            "visit_id": str(visit.id),
            "date": visit.created_at.date().isoformat(),
            "state": visit.state,
            "template": template_names.get(visit.template_id, "—"),
            "diagnoses": [
                {"text": item.suggestion_text, "code": item.code_value, "system": item.code_system}
                for item in resolved if item.kind == "clinical_dx"
            ],
            "medications": [
                {"text": item.suggestion_text, "code": item.code_value}
                for item in resolved if item.kind == "clinical_rx"
            ],
            "procedures": [
                {"text": item.suggestion_text, "code": item.code_value}
                for item in resolved if item.kind in ("clinical_procedure", "clinical_service")
            ],
            "summary_digest": _digest(sections),
        })
    return out


def build_context(
    db: Session,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    exclude_visit_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """لقطة ملف المريض التي تُحفظ مع الزيارة وتُغذّي P3 — مبنية من المراجعات السابقة وحدها.

    لا يُختلق شيء: إن لم تكن هناك مراجعة سابقة فالقوائم فارغة و`has_history=False`،
    وعلى الإرشاد أن يعتمد كلام الزيارة الحالية فقط.
    """
    history = previous_visits(db, patient_id, doctor_id, exclude_visit_id)

    problems: list[str] = []
    medications: list[str] = []
    for entry in history:                       # الأحدث أولاً — أول ذكر يبقى
        for diagnosis in entry["diagnoses"]:
            label = diagnosis["text"] if not diagnosis["code"] else f"{diagnosis['text']} ({diagnosis['code']})"
            if label not in problems:
                problems.append(label)
        for medication in entry["medications"]:
            if medication["text"] not in medications:
                medications.append(medication["text"])

    return {
        "source": "medify_history",   # لا ربط حي بنظام المستشفى بعد (D-09/INTEGRATION_ENGINE)
        "has_history": bool(history),
        "visits_count": len(history),
        "last_visit": history[0]["date"] if history else None,
        "previous_visits": history,
        "problems": problems,
        "medications": medications,
        "allergies": [],              # لا مصدر موثوق داخل ميديفاي — تبقى فارغة بدل اختلاقها
    }
