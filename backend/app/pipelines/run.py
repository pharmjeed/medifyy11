"""تشغيل خطوط المعالجة P2..P5 على الزيارة — كلها عبر طبقة الخدمة (DOC-08 مقفول)."""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import track
from ..errors import MedifyError
from ..models import (
    CodingSystemConfig,
    GuidanceItem,
    Patient,
    PatientContextSnapshot,
    Summary,
    SummarySection,
    Template,
    Transcript,
    Visit,
)
from ..notify import notify
from .deidentify import build_map
from .llm import get_llm

logger = logging.getLogger("medify.pipelines")

PROMPT_VERSIONS = {
    "P2-summary": "1.0",
    "P3-guidance": "1.0",
    "P4-reverse-template": "1.0",
    "P5-edit-chat": "1.0",
}


def _transcript_text(transcript: Transcript) -> str:
    segments = (transcript.content_json or {}).get("segments", [])
    return "\n".join(segment.get("text", "") for segment in segments)


def _active_coding_systems(db: Session, facility_id: uuid.UUID) -> list[str]:
    rows = db.execute(
        select(CodingSystemConfig).where(
            CodingSystemConfig.facility_id == facility_id,
            CodingSystemConfig.is_active == True,  # noqa: E712
        )
    ).scalars().all()
    return [row.system for row in rows] or ["ICD10AM"]


def run_summary(db: Session, visit: Visit) -> Summary:
    """P2 — التلخيص بالقالب. فشل بعد إعادة المحاولة → MDF-5032 (إعادة المحاولة داخل المحرك)."""
    transcript = db.execute(select(Transcript).where(Transcript.visit_id == visit.id)).scalar_one()
    template = db.execute(select(Template).where(Template.id == visit.template_id)).scalar_one()
    patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one()

    deid = build_map(patient.display_name, patient.hospital_mrn)
    version = PROMPT_VERSIONS["P2-summary"]
    try:
        output, model_ref = get_llm().complete_json(
            "P2-summary",
            version,
            {
                "transcript": deid.scrub(_transcript_text(transcript)),
                "template_structure": template.structure_json,
                "specialty": template.specialty or "",
                "visit_type": template.visit_type or "",
            },
        )
        sections_out = output["sections"]
        assert isinstance(sections_out, list) and sections_out
    except Exception as exc:
        logger.error("P2 فشل للزيارة %s: %s", visit.id, exc)
        raise MedifyError("MDF-5032", details={"visit_id": str(visit.id)}) from exc

    summary = Summary(
        visit_id=visit.id,
        facility_id=visit.facility_id,
        model_ref=model_ref,
        generated_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(summary)
    db.flush()
    for index, section in enumerate(sections_out):
        content = deid.restore(str(section.get("content", "")))
        db.add(
            SummarySection(
                summary_id=summary.id,
                facility_id=visit.facility_id,
                section_key=str(section.get("section_key", f"X{index}")),
                position=index,
                content_current=content,
                content_original=content,
            )
        )
    db.flush()
    track(
        "summary.generated", visit.facility_id, "doctor", visit.id,
        sections_count=len(sections_out), prompt_version=version, model_ref=model_ref,
    )
    return summary


def run_guidance(db: Session, visit: Visit, summary: Summary) -> bool:
    """P3 — الإرشاد المدمج. الفشل لا يحجب التدفق: ملخص بلا إرشادات + W-224 (MDF-5033)."""
    sections = db.execute(
        select(SummarySection).where(SummarySection.summary_id == summary.id).order_by(SummarySection.position)
    ).scalars().all()
    snapshot = None
    if visit.context_snapshot_id:
        snapshot = db.execute(
            select(PatientContextSnapshot).where(PatientContextSnapshot.id == visit.context_snapshot_id)
        ).scalar_one_or_none()
    transcript = db.execute(select(Transcript).where(Transcript.visit_id == visit.id)).scalar_one_or_none()
    patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one()

    deid = build_map(patient.display_name, patient.hospital_mrn)
    systems = _active_coding_systems(db, visit.facility_id)
    version = PROMPT_VERSIONS["P3-guidance"]
    by_key = {section.section_key: section for section in sections}

    try:
        output, _model_ref = get_llm().complete_json(
            "P3-guidance",
            version,
            {
                "summary_sections": [
                    {"section_key": s.section_key, "content": deid.scrub(s.content_current)} for s in sections
                ],
                "patient_context": deid.scrub(str((snapshot.content_json if snapshot else {}) or {})),
                "transcript_highlights": deid.scrub(_transcript_text(transcript)[:2000] if transcript else ""),
                "active_coding_systems": ", ".join(systems),
            },
        )
        items = output["items"]
        assert isinstance(items, list)
    except Exception as exc:
        logger.error("P3 فشل للزيارة %s: %s", visit.id, exc)
        notify(db, visit.facility_id, visit.doctor_id, "dr.analysis_failed", {"visit_id": str(visit.id), "mdf": "MDF-5033"})
        track("error.5xx", visit.facility_id, "doctor", visit.id, mdf_code="MDF-5033", pipeline_id="P3")
        return False

    counts_by_kind: dict[str, int] = {}
    per_section: dict[str, int] = {}
    safety_flags = 0
    for item in items:
        key = str(item.get("section_key", ""))
        section = by_key.get(key)
        if section is None:
            continue  # لا إرشاد بلا فقرة (ترشيح DOC-08 §٣)
        if not item.get("evidence_source") or not item.get("evidence_ref"):
            continue  # لا اقتراح بلا تعليل — قاعدة حاكمة
        if per_section.get(key, 0) >= 3:
            continue  # حد أقصى 3 إرشادات لكل فقرة (DOC-15 §٣)
        per_section[key] = per_section.get(key, 0) + 1
        kind = str(item.get("kind", "coding_match"))
        counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
        safety = bool(item.get("safety_flag"))
        safety_flags += 1 if safety else 0
        code_system = item.get("code_system")
        if code_system is not None and code_system not in systems:
            code_system = systems[0]  # الصياغة بمصطلحات النظام النشط حصراً
        db.add(
            GuidanceItem(
                section_id=section.id,
                facility_id=visit.facility_id,
                kind=kind,
                suggestion_text=deid.restore(str(item.get("suggestion_text", ""))),
                code_system=code_system,
                code_value=item.get("code_value"),
                evidence_source=str(item.get("evidence_source")),
                evidence_ref={"ref": deid.restore(str(item.get("evidence_ref", ""))), "safety_flag": safety},
                status="pending",
            )
        )
    db.flush()
    if safety_flags:
        notify(db, visit.facility_id, visit.doctor_id, "dr.safety_flag", {"visit_id": str(visit.id), "count": safety_flags})
    track("guidance.shown", visit.facility_id, "doctor", visit.id, counts_by_kind=counts_by_kind, safety_flags=safety_flags)
    return True


def run_reverse_template(
    sample_text: str, specialty: str, attachment: dict[str, Any] | None = None
) -> dict[str, Any]:
    """P4 — البناء العكسي من نص أو من مرفق (صورة/PDF). الفشل → MDF-5034. لا يُحفظ تلقائياً (FR-502)."""
    sample_for_prompt = sample_text.strip()
    if not sample_for_prompt and attachment is not None:
        kind = "PDF" if attachment.get("media_type") == "application/pdf" else "صورة"
        sample_for_prompt = f"(مثال الملاحظة مُرفق ك{kind} بهذه الرسالة — استنتج البنية من تخطيط المرفق وعناوين أقسامه.)"
    try:
        output, _model_ref = get_llm().complete_json(
            "P4-reverse-template",
            PROMPT_VERSIONS["P4-reverse-template"],
            {"sample_text": sample_for_prompt, "specialty": specialty},
            attachments=[attachment] if attachment is not None else None,
        )
        assert output.get("sections"), "بنية ناقصة"
        return output
    except Exception as exc:
        raise MedifyError("MDF-5034") from exc


def run_edit_chat(
    db: Session, visit: Visit, message: str, history: list[dict[str, Any]]
) -> dict[str, Any]:
    """P5 — محادثة التعديل الختامية. الغموض = سؤال توضيحي بلا patch."""
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one()
    sections = db.execute(
        select(SummarySection).where(SummarySection.summary_id == summary.id).order_by(SummarySection.position)
    ).scalars().all()
    try:
        output, _model_ref = get_llm().complete_json(
            "P5-edit-chat",
            PROMPT_VERSIONS["P5-edit-chat"],
            {
                "message": message,
                "summary_sections_current": [
                    {"section_key": s.section_key, "content": s.content_current} for s in sections
                ],
                "chat_history": history,
            },
        )
    except Exception as exc:
        raise MedifyError("MDF-5034") from exc

    applied: list[dict[str, Any]] = []
    by_key = {section.section_key: section for section in sections}
    for patch in output.get("patches", []):
        section = by_key.get(str(patch.get("section_key", "")))
        if section is None:
            continue
        new_content = str(patch.get("new_content", ""))
        if not new_content:
            continue
        old_content = section.content_current
        section.content_current = new_content
        applied.append(
            {
                "section_id": str(section.id),
                "section_key": section.section_key,
                "old_content": old_content,
                "new_content": new_content,
            }
        )
    db.flush()
    return {"reply": str(output.get("reply", "")), "patches": applied}
