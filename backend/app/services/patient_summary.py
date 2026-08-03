"""ملخص المريض بالعربي (م14) — يتولّد بعد البوابة ① حصراً.

الحياة الدورية: يُولَّد بعد ① · يعاينه الطبيب ويعدّله ويقرر تضمينه (toggle) قبل
النقل · يُخزَّن مع النسخة (م6) فreopen يعيد توليده لنسخته · unlock يجعله stale
(بصمة النص تغيّرت) حتى إعادة الاعتماد.

مسودة النسخة قبل البوابة ② هي حاملة الملخص — لذا تُنشأ عند أول توليد إن غابت.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import MedifyError
from ..models import NoteVersion, Visit
from ..pipelines.llm import get_llm
from .versions import live_codes_snapshot, live_sections_snapshot
from .visits import active_note_approval, summary_hashes

logger = logging.getLogger("medify.patient_summary")

PROMPT_ID = "P6-patient-summary"
PROMPT_VERSION = "1.0"
SECTIONS = ("diagnosis", "medications", "instructions", "follow_up", "red_flags")


def _version_row(db: Session, visit: Visit) -> NoteVersion | None:
    return db.execute(
        select(NoteVersion).where(
            NoteVersion.visit_id == visit.id,
            NoteVersion.version_number == visit.cycle,
        )
    ).scalar_one_or_none()


def _ensure_version_row(db: Session, visit: Visit) -> NoteVersion:
    """صف النسخة الحالية — يُنشأ مسودةً إن لم يوجد (v1 قبل البوابة ②)."""
    row = _version_row(db, visit)
    if row is None:
        row = NoteVersion(
            visit_id=visit.id,
            facility_id=visit.facility_id,
            version_number=visit.cycle,
            note_snapshot={"sections": live_sections_snapshot(db, visit)},
            approved_codes_snapshot={"codes": live_codes_snapshot(db, visit)},
            upload_status="draft",
        )
        db.add(row)
        db.flush()
    return row


def generate_patient_summary(db: Session, visit: Visit) -> dict[str, Any]:
    """توليد الملخص — 403 قبل البوابة ① (الحارس في طبقة الخدمة لا الواجهة)."""
    if active_note_approval(db, visit) is None:
        raise MedifyError("MDF-4231", details={"reason": "patient_summary_requires_gate_1"})

    sections = live_sections_snapshot(db, visit)
    codes = live_codes_snapshot(db, visit)
    output, _model_ref = get_llm().complete_json(
        PROMPT_ID, PROMPT_VERSION,
        {
            "note_sections": [{"section_key": s["section_key"], "content": s["content"]} for s in sections],
            "approved_codes": [
                {"kind": c["kind"], "code_system": c["code_system"], "code_value": c["code_value"],
                 "text": c["suggestion_text"]}
                for c in codes
            ],
        },
    )
    summary = {key: str(output.get(key, "") or "") for key in SECTIONS}
    content_hash, _codes_hash = summary_hashes(db, visit)

    row = _ensure_version_row(db, visit)
    row.patient_summary_json = summary
    row.patient_summary_note_hash = content_hash
    db.flush()
    return summary


def get_patient_summary(db: Session, visit: Visit) -> dict[str, Any] | None:
    """الملخص المخزَّن مع حالته — stale إن تغيّر النص بعد التوليد (unlock/تعديل)."""
    row = _version_row(db, visit)
    if row is None or not row.patient_summary_json:
        return None
    try:
        current_hash, _codes = summary_hashes(db, visit)
    except Exception:  # لا ملخص سريري بعد — لا مقارنة
        current_hash = None
    return {
        "summary": row.patient_summary_json,
        "included": row.patient_summary_included,
        "stale": bool(current_hash and row.patient_summary_note_hash
                      and current_hash != row.patient_summary_note_hash),
        "version_number": row.version_number,
    }


def update_patient_summary(db: Session, visit: Visit, *, summary: dict[str, Any] | None = None,
                           included: bool | None = None) -> dict[str, Any]:
    """تعديل الطبيب للنص و/أو قراره بالتضمين — قبل النقل فقط (النسخة المنقولة مجمّدة)."""
    row = _version_row(db, visit)
    if row is None or not row.patient_summary_json:
        raise MedifyError("MDF-4041", details={"reason": "patient_summary_not_generated"})
    if row.upload_status == "uploaded":
        raise MedifyError("MDF-4226", details={"reason": "uploaded_version_is_immutable"})
    if summary is not None:
        merged = dict(row.patient_summary_json)
        for key in SECTIONS:
            if key in summary:
                merged[key] = str(summary[key] or "")
        row.patient_summary_json = merged
        # تعديل الطبيب يُثبّت الملخص على النص الحالي — لا يبقى stale بعد مراجعته
        content_hash, _codes = summary_hashes(db, visit)
        row.patient_summary_note_hash = content_hash
    if included is not None:
        row.patient_summary_included = included
    db.flush()
    result = get_patient_summary(db, visit)
    assert result is not None
    return result


def regenerate_for_new_version(db: Session, visit: Visit) -> None:
    """بعد reopen: النسخة الجديدة تبدأ بلا ملخص — يُعاد توليده بعد بوابتها ①."""
    row = _version_row(db, visit)
    if row is None:
        return
    row.patient_summary_json = None
    row.patient_summary_note_hash = None
    row.patient_summary_included = False
    db.flush()
