"""قوالب التلخيص القياسية — تُبذر لكل منشأة جديدة عند إنشائها.

بلا هذه القوالب لا يستطيع الدكتور بدء زيارة إطلاقاً (اختيار القالب خطوة إلزامية
في W-211)، فالمنشأة الجديدة كانت تُولد معطّلة عملياً. المصدر: نفس بنية قوالب
النظام في scripts/seed.py — SOAP هي القالب الافتراضي المعتمد (DOC-10 W-203).

الأقسام تُبنى ديناميكياً من `structure_json` (قرار مالك 2026-07-14) — لا S/O/A/P
مثبتة في الكود؛ هذه القوالب مجرد بذرة قابلة للتعديل والحذف من حساب الدكتور.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import Template

_SOAP_SECTIONS: list[dict[str, str]] = [
    {"section_key": "S", "title": "الذاتي — Subjective",
     "instructions": "Summarize the patient's complaints, timeline, and adherence in the patient's voice."},
    {"section_key": "O", "title": "الموضوعي — Objective",
     "instructions": "Record vital signs and focused examination findings stated by the clinician."},
    {"section_key": "A", "title": "التقييم — Assessment",
     "instructions": "Document the clinician's stated assessment only — no inferred diagnoses."},
    {"section_key": "P", "title": "الخطة — Plan",
     "instructions": "List medications, investigations, monitoring, and follow-up interval as stated."},
]

_HISTORY_SECTION = {
    "section_key": "H", "title": "التاريخ المرضي — History",
    "instructions": "Capture relevant past medical, family, and social history mentioned during the first visit.",
}
_EDUCATION_SECTION = {
    "section_key": "E", "title": "تثقيف المريض — Patient education",
    "instructions": "One line of patient-directed education and safety-net advice.",
}

SOAP4: dict[str, Any] = {"sections": _SOAP_SECTIONS}
SOAP5_FIRST: dict[str, Any] = {"sections": [*_SOAP_SECTIONS, _HISTORY_SECTION]}
SOAP5_EDU: dict[str, Any] = {"sections": [*_SOAP_SECTIONS, _EDUCATION_SECTION]}

# (الاسم، التخصص، نوع الزيارة، البنية، هل هو الافتراضي)
# التخصص None = متاح لكل التخصصات (قوالب عامة على مستوى المنشأة)
DEFAULT_TEMPLATES: list[tuple[str, str | None, str, dict[str, Any], bool]] = [
    ("SOAP — متابعة عامة", None, "متابعة", SOAP4, True),
    ("SOAP — كشف أول", None, "كشف أول", SOAP5_FIRST, False),
    ("SOAP — استشارة", None, "استشارة", SOAP4, False),
    ("SOAP + تثقيف المريض", None, "متابعة", SOAP5_EDU, False),
]


def seed_default_templates(db: Session, facility_id: Any) -> int:
    """يبذر القوالب القياسية للمنشأة — قوالب نظام (origin=system) بلا مالك.

    تُستدعى من مساري إنشاء المنشأة (التسجيل الذاتي W-002 وإنشاء المنصة)،
    وتعيد عدد القوالب المُنشأة.
    """
    for name, specialty, visit_type, structure, is_default in DEFAULT_TEMPLATES:
        db.add(Template(
            facility_id=facility_id,
            owner_user_id=None,       # قالب منشأة عام — لا مالك
            name=name,
            specialty=specialty,
            visit_type=visit_type,
            structure_json=structure,
            origin="system",
            is_default=is_default,
        ))
    db.flush()
    return len(DEFAULT_TEMPLATES)
