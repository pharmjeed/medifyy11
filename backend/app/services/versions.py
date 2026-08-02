"""دورة النسخ (م6) — لقطات note_versions + diff + reopen.

المبدآن 2/3: التعديل بعد النقل = reopen → مسودة v+1 → البوابتان → نقل بدلالة
replace؛ والنسخ المنقولة لقطات immutable (trigger 0014 يرفض UPDATE بعد uploaded).
"""
from __future__ import annotations

import datetime as dt
import difflib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import MedifyError
from ..models import (
    Approval,
    GuidanceItem,
    NoteApproval,
    NoteVersion,
    Summary,
    SummarySection,
    Visit,
)
from .fhir import bundle_hash as compute_bundle_hash


def live_sections_snapshot(db: Session, visit: Visit) -> list[dict]:
    """نص الأقسام الحي كما هو الآن — يصير اللقطة المعتمدة لحظة البوابة ②."""
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one()
    sections = db.execute(
        select(SummarySection)
        .where(SummarySection.summary_id == summary.id)
        .order_by(SummarySection.position)
    ).scalars().all()
    return [
        {"section_key": s.section_key, "position": s.position, "content": s.content_current}
        for s in sections
    ]


def live_codes_snapshot(db: Session, visit: Visit) -> list[dict]:
    """الأكواد المعتمدة (accepted|modified) — ما سينتقل فعلاً لنظام المستشفى."""
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one()
    items = db.execute(
        select(GuidanceItem)
        .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
        .where(
            SummarySection.summary_id == summary.id,
            GuidanceItem.status.in_(["accepted", "modified"]),
        )
        .order_by(GuidanceItem.id)
    ).scalars().all()
    return [
        {
            "kind": item.kind,
            "code_system": item.code_system,
            "code_value": item.code_value,
            "code_secondary_system": item.code_secondary_system,
            "code_secondary_value": item.code_secondary_value,
            "linked_dx_code": item.linked_dx_code,
            "suggestion_text": item.suggestion_text,
            "status": item.status,
            # وفاء المخارج من اللقطة (م6): التبرير وبيانات السجل المرجعي تُحفظ حرفياً
            "justification": item.justification,
            "code_registry_version": item.code_registry_version,
            "code_effective_date": item.code_effective_date,
            "requires_doctor_input": item.requires_doctor_input,
        }
        for item in items
    ]


def _code_key(code: dict) -> tuple:
    return (code.get("code_system") or "", code.get("code_value") or "")


def compute_version_diff(prev_sections: list[dict], prev_codes: list[dict],
                         new_sections: list[dict], new_codes: list[dict]) -> dict:
    """diff نصي لكل قسم + diff أكواد — يُخزَّن مشفراً مع النسخة؛ Audit يأخذ الأعداد فقط."""
    prev_by_key = {s["section_key"]: s.get("content", "") for s in prev_sections}
    new_by_key = {s["section_key"]: s.get("content", "") for s in new_sections}
    section_diffs: list[dict] = []
    changed = 0
    for key in sorted(set(prev_by_key) | set(new_by_key)):
        old_text = prev_by_key.get(key, "")
        new_text = new_by_key.get(key, "")
        if old_text == new_text:
            continue
        changed += 1
        unified = "\n".join(difflib.unified_diff(
            old_text.splitlines(), new_text.splitlines(),
            fromfile=f"{key}@prev", tofile=f"{key}@new", lineterm="",
        ))
        section_diffs.append({"section_key": key, "unified": unified})

    prev_keys = {_code_key(c) for c in prev_codes}
    new_keys = {_code_key(c) for c in new_codes}
    added = [c for c in new_codes if _code_key(c) not in prev_keys]
    removed = [c for c in prev_codes if _code_key(c) not in new_keys]
    return {
        "sections": section_diffs,
        "codes": {"added": added, "removed": removed},
        "counts": {
            "sections_changed": changed,
            "codes_added": len(added),
            "codes_removed": len(removed),
        },
    }


def get_version(db: Session, visit_id: uuid.UUID, version_number: int) -> NoteVersion | None:
    return db.execute(
        select(NoteVersion).where(
            NoteVersion.visit_id == visit_id,
            NoteVersion.version_number == version_number,
        )
    ).scalar_one_or_none()


def latest_uploaded_version(db: Session, visit_id: uuid.UUID) -> NoteVersion | None:
    return db.execute(
        select(NoteVersion)
        .where(NoteVersion.visit_id == visit_id, NoteVersion.upload_status == "uploaded")
        .order_by(NoteVersion.version_number.desc())
    ).scalars().first()


def start_reopen_draft(db: Session, visit: Visit, reason: str) -> NoteVersion:
    """مسودة v+1 عند reopen — نسخة من لقطة الأخيرة المنقولة + سبب الفتح مشفراً.

    تُستدعى بعد رفع visit.cycle: version_number = الدورة الجديدة.
    """
    previous = latest_uploaded_version(db, visit.id)
    if previous is None:
        raise MedifyError("MDF-4223", details={"reason": "no_uploaded_version_to_reopen"})
    draft = NoteVersion(
        visit_id=visit.id,
        facility_id=visit.facility_id,
        version_number=visit.cycle,
        note_snapshot=previous.note_snapshot,
        approved_codes_snapshot=previous.approved_codes_snapshot,
        upload_status="draft",
        reopen_reason=reason,
    )
    db.add(draft)
    db.flush()
    return draft


def finalize_version(db: Session, visit: Visit, note_approval: NoteApproval,
                     approval: Approval, bundle: dict) -> NoteVersion:
    """اكتمال النسخة لحظة البوابة ②: اللقطات الحرفية + بصمة الحزمة + طوابع البوابتين + diff.

    v1 تُنشأ هنا؛ v≥2 مسودتها قائمة من reopen فتُستكمل. الصف يتجمد نهائياً عند uploaded.
    """
    version_number = visit.cycle
    sections = live_sections_snapshot(db, visit)
    codes = live_codes_snapshot(db, visit)

    row = get_version(db, visit.id, version_number)
    if row is None:
        row = NoteVersion(
            visit_id=visit.id,
            facility_id=visit.facility_id,
            version_number=version_number,
        )
        db.add(row)
    row.note_snapshot = {"sections": sections}
    row.approved_codes_snapshot = {"codes": codes}
    row.bundle_hash = compute_bundle_hash(bundle)
    row.note_approved_at = note_approval.approved_at
    row.note_approved_by = note_approval.approved_by
    row.codes_approved_at = approval.approved_at
    row.codes_approved_by = approval.approved_by
    row.upload_status = "pending"

    if version_number > 1:
        previous = get_version(db, visit.id, version_number - 1)
        if previous is not None:
            prev_sections = (previous.note_snapshot or {}).get("sections", [])
            prev_codes = (previous.approved_codes_snapshot or {}).get("codes", [])
            row.diff_json = compute_version_diff(prev_sections, prev_codes, sections, codes)

    db.flush()
    return row


def mark_version_upload_result(db: Session, visit_id: uuid.UUID, version_number: int, ok: bool) -> None:
    """نتيجة الرفع على صف النسخة — النجاح يجمّده للأبد (trigger 0014)."""
    row = get_version(db, visit_id, version_number)
    if row is None or row.upload_status == "uploaded":
        return
    if ok:
        row.upload_status = "uploaded"
        row.uploaded_at = dt.datetime.now(dt.timezone.utc)
    else:
        row.upload_status = "upload_failed"
    db.flush()
