"""الملخص والإرشاد والتحرير الثلاثي — DOC-05 §٤ (FR-700)."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...analytics import track
from ...deps import DoctorAuth, DB
from ...envelope import ok
from ...errors import MedifyError
from ...models import (
    Approval,
    EditEvent,
    GuidanceItem,
    NoteApproval,
    Summary,
    SummarySection,
    Visit,
)
from ...pipelines.run import run_edit_chat
from ...pipelines.stt import get_stt
from ...services.visits import get_visit_for_doctor, summary_etag

router = APIRouter()


def _get_summary(db, visit: Visit) -> Summary:
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    if summary is None:
        raise MedifyError("MDF-4041")
    return summary


def _guard_not_approved(db, visit: Visit) -> None:
    """حسم الأكواد مفتوح حتى البوابة ② — يُغلق بعدها فقط."""
    approval = db.execute(select(Approval).where(Approval.visit_id == visit.id)).scalar_one_or_none()
    if approval is not None or visit.state in ("approved", "uploaded", "upload_failed"):
        raise MedifyError("MDF-4226")


def _guard_note_open(db, visit: Visit) -> None:
    """تحرير نص المذكرة يُغلق عند البوابة ① — وإلا بطلت بصمة ما اعتُمد (trigger القاعدة يفرضها)."""
    _guard_not_approved(db, visit)
    note_approval = db.execute(
        select(NoteApproval).where(NoteApproval.visit_id == visit.id)
    ).scalar_one_or_none()
    if note_approval is not None:
        raise MedifyError("MDF-4226", details={"reason": "note_approved_gate_1"})


def _check_etag(request: Request, db, visit: Visit) -> None:
    """If-Match إلزامي على تعديلات الملخص — تعارض → MDF-4224 (D-13)."""
    provided = request.headers.get("If-Match")
    if not provided:
        raise MedifyError("MDF-4224", details={"reason": "missing_if_match"})
    current = summary_etag(db, visit)
    if provided.strip('"') != current:
        raise MedifyError("MDF-4224", details={"current_etag": current})


@router.get("/visits/{visit_id}/summary")
def get_summary(visit_id: uuid.UUID, ctx: DoctorAuth, db: DB, response: Response):
    """الملخص بأقسامه + الإرشادات المضمّنة لكل قسم + ETag (FR-701/702/703)."""
    visit = get_visit_for_doctor(db, visit_id)
    summary = _get_summary(db, visit)
    sections = db.execute(
        select(SummarySection).where(SummarySection.summary_id == summary.id).order_by(SummarySection.position)
    ).scalars().all()
    out_sections: list[dict[str, Any]] = []
    pending_total = 0
    for section in sections:
        items = db.execute(
            select(GuidanceItem).where(GuidanceItem.section_id == section.id).order_by(GuidanceItem.created_at)
        ).scalars().all()
        pending_total += sum(1 for item in items if item.status == "pending")
        out_sections.append({
            "id": str(section.id),
            "section_key": section.section_key,
            "position": section.position,
            "content_current": section.content_current,
            "content_original": section.content_original,
            "is_edited": section.content_current != section.content_original,
            "guidance": [
                {
                    "id": str(item.id),
                    "kind": item.kind,
                    "suggestion_text": item.suggestion_text,
                    # «لا تخمين»: دون العتبة لا يخرج الكود إطلاقاً — خانة فارغة وتنبيه
                    "code_system": None if item.requires_doctor_input else item.code_system,
                    "code_value": None if item.requires_doctor_input else item.code_value,
                    "code_secondary_system": None if item.requires_doctor_input else item.code_secondary_system,
                    "code_secondary_value": None if item.requires_doctor_input else item.code_secondary_value,
                    "code_registry_version": item.code_registry_version,
                    "code_effective_date": item.code_effective_date,
                    "confidence": item.confidence,
                    "requires_doctor_input": item.requires_doctor_input,
                    "linked_dx_code": item.linked_dx_code,
                    "justification": item.justification,
                    "evidence_source": item.evidence_source,
                    "evidence_ref": (item.evidence_ref or {}).get("ref"),
                    "safety_flag": bool((item.evidence_ref or {}).get("safety_flag")),
                    "status": item.status,
                }
                for item in items
            ],
        })
    etag = summary_etag(db, visit)
    response.headers["ETag"] = f'"{etag}"'
    # سجل الاعتماد الإلحاقي — يلزم عرض W-221 (قراءة فقط بعد الاعتماد)
    from ...models import User

    def _actor(user_id) -> str:
        row = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        return row.full_name if row else "—"

    note_approval = db.execute(
        select(NoteApproval).where(NoteApproval.visit_id == visit.id)
    ).scalar_one_or_none()
    approval = db.execute(select(Approval).where(Approval.visit_id == visit.id)).scalar_one_or_none()
    approval_out = None
    if approval is not None:
        approval_out = {
            "approved_by": _actor(approval.approved_by),
            "approved_at": approval.approved_at.isoformat(),
            "summary_hash": approval.summary_hash,
            "codes_hash": approval.codes_hash,
        }
    # بوابتان منفصلتان ببصمة لكل واحدة (توجيه المالك 2026-07-22)
    gates = {
        "note": None if note_approval is None else {
            "approved_by": _actor(note_approval.approved_by),
            "approved_at": note_approval.approved_at.isoformat(),
            "summary_hash": note_approval.summary_hash,
        },
        "codes": None if approval is None else {
            "approved_by": approval_out["approved_by"],
            "approved_at": approval_out["approved_at"],
            "codes_hash": approval.codes_hash,
        },
    }
    awaiting_input = sum(
        1 for section in out_sections for item in section["guidance"]
        if item["requires_doctor_input"] and item["status"] in ("accepted", "modified")
        and not item["code_value"]
    )
    return ok({
        "visit_id": str(visit.id),
        "state": visit.state,
        "model_ref": summary.model_ref,
        "generated_at": summary.generated_at.isoformat(),
        "sections": out_sections,
        "pending_guidance_count": pending_total,
        "awaiting_doctor_input_count": awaiting_input,
        "etag": etag,
        "gates": gates,
        "note_approved": note_approval is not None,
        "can_export": approval is not None,
        "approval": approval_out,
    })


class SectionPatchIn(BaseModel):
    content_current: str = Field(min_length=1)


@router.patch("/summary-sections/{section_id}")
def patch_section(section_id: uuid.UUID, body: SectionPatchIn, ctx: DoctorAuth, db: DB, request: Request, response: Response):
    """تحرير كتابي (FR-705) — يسجل edit_event(typing) · If-Match إلزامي."""
    section = db.execute(select(SummarySection).where(SummarySection.id == section_id)).scalar_one_or_none()
    if section is None:
        raise MedifyError("MDF-4041")
    summary = db.execute(select(Summary).where(Summary.id == section.summary_id)).scalar_one()
    visit = get_visit_for_doctor(db, summary.visit_id)
    _guard_note_open(db, visit)
    _check_etag(request, db, visit)

    old_content = section.content_current
    section.content_current = body.content_current
    db.add(EditEvent(
        visit_id=visit.id,
        section_id=section.id,
        facility_id=ctx.facility_id,
        channel="typing",
        payload_json={"old_len": len(old_content), "new_len": len(body.content_current)},
        actor_user_id=ctx.user_id,
    ))
    db.flush()
    track("edit.applied", ctx.facility_id, "doctor", visit.id,
          channel="typing", section_key=section.section_key,
          delta_chars=len(body.content_current) - len(old_content))
    new_etag = summary_etag(db, visit)
    response.headers["ETag"] = f'"{new_etag}"'
    return ok({"id": str(section.id), "content_current": section.content_current, "etag": new_etag})


class DictateIn(BaseModel):
    audio_b64: str | None = None
    mode: str = "append"  # append | replace


@router.post("/summary-sections/{section_id}/dictate")
def dictate_section(section_id: uuid.UUID, body: DictateIn, ctx: DoctorAuth, db: DB, request: Request, response: Response):
    """تحرير صوتي (FR-706): إملاء قصير → دمج في الفقرة — نفس نموذج P1."""
    section = db.execute(select(SummarySection).where(SummarySection.id == section_id)).scalar_one_or_none()
    if section is None:
        raise MedifyError("MDF-4041")
    summary = db.execute(select(Summary).where(Summary.id == section.summary_id)).scalar_one()
    visit = get_visit_for_doctor(db, summary.visit_id)
    _guard_note_open(db, visit)
    _check_etag(request, db, visit)

    dictated_text = get_stt().transcribe_file("dictation.opus")
    old_content = section.content_current
    if body.mode == "replace":
        section.content_current = dictated_text
    else:
        section.content_current = (old_content.rstrip() + " " + dictated_text).strip()
    db.add(EditEvent(
        visit_id=visit.id,
        section_id=section.id,
        facility_id=ctx.facility_id,
        channel="voice",
        payload_json={"dictated_len": len(dictated_text), "mode": body.mode},
        actor_user_id=ctx.user_id,
    ))
    db.flush()
    track("edit.applied", ctx.facility_id, "doctor", visit.id,
          channel="voice", section_key=section.section_key,
          delta_chars=len(section.content_current) - len(old_content))
    new_etag = summary_etag(db, visit)
    response.headers["ETag"] = f'"{new_etag}"'
    return ok({"id": str(section.id), "content_current": section.content_current, "dictated_text": dictated_text, "etag": new_etag})


class GuidancePatchIn(BaseModel):
    status: str  # accepted | rejected | modified
    modified_text: str | None = None
    modified_code_system: str | None = None
    modified_code_value: str | None = None


@router.patch("/guidance-items/{item_id}")
def resolve_guidance(item_id: uuid.UUID, body: GuidancePatchIn, ctx: DoctorAuth, db: DB):
    """حسم إرشاد (FR-704) — التعديل يشمل النص والرمز معاً (قرار مالك 2026-07-14)."""
    if body.status not in ("accepted", "rejected", "modified"):
        raise MedifyError("MDF-4041", details={"status": body.status})
    item = db.execute(select(GuidanceItem).where(GuidanceItem.id == item_id)).scalar_one_or_none()
    if item is None:
        raise MedifyError("MDF-4041")
    section = db.execute(select(SummarySection).where(SummarySection.id == item.section_id)).scalar_one()
    summary = db.execute(select(Summary).where(Summary.id == section.summary_id)).scalar_one()
    visit = get_visit_for_doctor(db, summary.visit_id)
    _guard_not_approved(db, visit)

    started = item.created_at
    if body.status == "modified":
        if not body.modified_text:
            raise MedifyError("MDF-4225", details={"missing": "modified_text"})
        item.suggestion_text = body.modified_text
        if body.modified_code_system is not None:
            item.code_system = body.modified_code_system
        if body.modified_code_value is not None:
            item.code_value = body.modified_code_value
        # الطبيب أدخل الكود بنفسه — الحجب دون العتبة يسقط بفعل واعٍ منه لا آلياً
        if item.requires_doctor_input and item.code_value:
            item.requires_doctor_input = False
            item.confidence = None  # الكود صار مُدخلاً بشرياً لا مقترحاً بثقة
            item.code_registry_version = None
            item.code_effective_date = None
    item.status = body.status
    item.resolved_by = ctx.user_id
    item.resolved_at = dt.datetime.now(dt.timezone.utc)
    db.flush()
    elapsed_ms = int((item.resolved_at - started).total_seconds() * 1000)
    track("guidance.resolved", ctx.facility_id, "doctor", visit.id,
          kind=item.kind, status=item.status, time_to_resolve_ms=elapsed_ms)
    return ok({
        "id": str(item.id),
        "status": item.status,
        "suggestion_text": item.suggestion_text,
        "code_system": item.code_system,
        "code_value": item.code_value,
        "requires_doctor_input": item.requires_doctor_input,
        "confidence": item.confidence,
    })


class AiChatIn(BaseModel):
    message: str = Field(min_length=1)
    history: list[dict[str, Any]] = []


@router.post("/visits/{visit_id}/ai-chat")
def ai_chat(visit_id: uuid.UUID, body: AiChatIn, ctx: DoctorAuth, db: DB, response: Response):
    """محادثة التعديل الختامية (FR-707) — رد + فروقات مطبقة، يسجل edit_event(ai_chat)."""
    visit = get_visit_for_doctor(db, visit_id)
    _guard_note_open(db, visit)
    result = run_edit_chat(db, visit, body.message, body.history)
    if result["patches"]:
        for patch in result["patches"]:
            db.add(EditEvent(
                visit_id=visit.id,
                section_id=uuid.UUID(patch["section_id"]),
                facility_id=ctx.facility_id,
                channel="ai_chat",
                payload_json={"request": body.message, "reply": result["reply"],
                              "old_content": patch["old_content"], "new_content": patch["new_content"]},
                actor_user_id=ctx.user_id,
            ))
            track("edit.applied", ctx.facility_id, "doctor", visit.id,
                  channel="ai_chat", section_key=patch["section_key"],
                  delta_chars=len(patch["new_content"]) - len(patch["old_content"]))
        db.flush()
    new_etag = summary_etag(db, visit)
    response.headers["ETag"] = f'"{new_etag}"'
    return ok({"reply": result["reply"], "patches": result["patches"], "etag": new_etag})
