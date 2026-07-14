"""القوالب — DOC-05 §٤ (FR-500): القائمة + البناء العكسي + المعاينة + الحفظ + الافتراضي."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from ...analytics import track
from ...deps import Auth, DoctorAuth, DB
from ...envelope import ok
from ...errors import MedifyError
from ...models import Template
from ...pipelines.llm import get_llm
from ...pipelines.run import PROMPT_VERSIONS, run_reverse_template

router = APIRouter()


def _template_out(template: Template) -> dict[str, Any]:
    return {
        "id": str(template.id),
        "name": template.name,
        "specialty": template.specialty,
        "visit_type": template.visit_type,
        "structure": template.structure_json,
        "origin": template.origin,
        "is_default": template.is_default,
        "is_personal": template.owner_user_id is not None,
        "archived_at": template.archived_at.isoformat() if template.archived_at else None,
    }


@router.get("/templates")
def list_templates(ctx: Auth, db: DB, include_archived: bool = False):
    """الجاهزة (العامة) + الشخصية — RLS يفلتر شخصيات الآخرين (FR-501)."""
    query = select(Template).where(Template.facility_id == ctx.facility_id)
    if not include_archived:
        query = query.where(Template.archived_at.is_(None))
    templates = db.execute(query.order_by(Template.created_at)).scalars().all()
    return ok([_template_out(template) for template in templates])


def _validate_structure(structure: dict[str, Any]) -> None:
    """بنية ناقصة → MDF-4225 (DOC-13)."""
    sections = structure.get("sections")
    if not isinstance(sections, list) or not sections:
        raise MedifyError("MDF-4225", details={"missing": "sections"})
    seen_keys: set[str] = set()
    for section in sections:
        key = section.get("section_key")
        if not key or not section.get("title") or not section.get("instructions"):
            raise MedifyError("MDF-4225", details={"section": section})
        if key in seen_keys:
            raise MedifyError("MDF-4225", details={"duplicate_key": key})
        seen_keys.add(key)


class ReverseBuildIn(BaseModel):
    sample_text: str = Field(min_length=20)
    summarization_style: str = Field(min_length=3)


@router.post("/templates/reverse-build")
def reverse_build(body: ReverseBuildIn, ctx: DoctorAuth, db: DB):
    """P4 — يولّد البنية ولا يحفظ تلقائياً (FR-502)."""
    structure = run_reverse_template(body.sample_text, body.summarization_style, ctx.user.specialty or "")
    track("template.reverse_built", ctx.facility_id, "doctor", saved=False, preview_iterations=0)
    return ok({"name": structure.get("name", ""), "structure": {"sections": structure["sections"]}})


class PreviewIn(BaseModel):
    structure: dict[str, Any]
    sample_transcript: str | None = None


@router.post("/templates/preview")
def preview_template(body: PreviewIn, ctx: DoctorAuth, db: DB):
    """معاينة القالب على نص تجريبي قياسي (FR-503)."""
    _validate_structure(body.structure)
    default_transcript = (
        "المريض يشتكي من صداع من خمسة أيام مع دوخة خفيفة، وما كان منتظم على علاج الضغط. "
        "القياس 165/95 والنبض 82. التقييم: ضغط غير منضبط. الخطة: أملوديبين 5 ملجم يومياً ومتابعة بعد أسبوعين."
    )
    output, _model_ref = get_llm().complete_json(
        "P2-summary",
        PROMPT_VERSIONS["P2-summary"],
        {
            "transcript": body.sample_transcript or default_transcript,
            "template_structure": body.structure,
            "specialty": ctx.user.specialty or "",
            "visit_type": "preview",
        },
    )
    return ok({"sections": output.get("sections", [])})


class TemplateSaveIn(BaseModel):
    name: str = Field(min_length=2)
    specialty: str | None = None
    visit_type: str | None = None
    structure: dict[str, Any]
    origin: str = "reverse_built"
    source_sample_text: str | None = None
    scope: str = "personal"  # personal | facility (الأدمن فقط للعامة)


@router.post("/templates", status_code=201)
def save_template(body: TemplateSaveIn, ctx: Auth, db: DB):
    _validate_structure(body.structure)
    if body.origin not in ("system", "reverse_built"):
        raise MedifyError("MDF-4225", details={"origin": body.origin})
    if body.scope == "facility":
        if ctx.role != "admin":
            raise MedifyError("MDF-4031")
        owner_id = None
    else:
        if ctx.role != "doctor":
            raise MedifyError("MDF-4031")
        owner_id = ctx.user_id
    template = Template(
        facility_id=ctx.facility_id,
        owner_user_id=owner_id,
        name=body.name,
        specialty=body.specialty or ctx.user.specialty,
        visit_type=body.visit_type,
        structure_json=body.structure,
        origin=body.origin,
        source_sample_text=body.source_sample_text,
    )
    db.add(template)
    db.flush()
    if body.origin == "reverse_built":
        track("template.reverse_built", ctx.facility_id, ctx.role, saved=True, preview_iterations=1)
    return ok(_template_out(template))


class TemplatePatchIn(BaseModel):
    name: str | None = None
    specialty: str | None = None
    visit_type: str | None = None
    structure: dict[str, Any] | None = None


def _get_owned_template(db, ctx, template_id: uuid.UUID) -> Template:
    template = db.execute(select(Template).where(Template.id == template_id)).scalar_one_or_none()
    if template is None:
        raise MedifyError("MDF-4041")
    if ctx.role == "doctor" and template.owner_user_id != ctx.user_id:
        raise MedifyError("MDF-4031")  # لا يعدل دكتور قالباً عاماً أو قالب غيره
    if ctx.role == "admin" and template.owner_user_id is not None:
        raise MedifyError("MDF-4041")
    return template


@router.patch("/templates/{template_id}")
def update_template(template_id: uuid.UUID, body: TemplatePatchIn, ctx: Auth, db: DB):
    template = _get_owned_template(db, ctx, template_id)
    if body.structure is not None:
        _validate_structure(body.structure)
        template.structure_json = body.structure
    if body.name is not None:
        template.name = body.name
    if body.specialty is not None:
        template.specialty = body.specialty
    if body.visit_type is not None:
        template.visit_type = body.visit_type
    return ok(_template_out(template))


@router.delete("/templates/{template_id}")
def delete_template(template_id: uuid.UUID, ctx: Auth, db: DB):
    """حذف = أرشفة ناعمة (FR-504) — يبقى مرجعاً للزيارات السابقة."""
    template = _get_owned_template(db, ctx, template_id)
    template.archived_at = dt.datetime.now(dt.timezone.utc)
    return ok({"archived": True})


@router.patch("/templates/{template_id}/default")
def set_default_template(template_id: uuid.UUID, ctx: DoctorAuth, db: DB):
    """تعيين قالب افتراضي للدكتور (FR-505)."""
    template = db.execute(select(Template).where(Template.id == template_id)).scalar_one_or_none()
    if template is None or template.archived_at is not None:
        raise MedifyError("MDF-4041")
    for personal in db.execute(
        select(Template).where(Template.owner_user_id == ctx.user_id, Template.is_default == True)  # noqa: E712
    ).scalars():
        personal.is_default = False
    if template.owner_user_id == ctx.user_id:
        template.is_default = True
        return ok(_template_out(template))
    raise MedifyError("MDF-4031", details={"reason": "only_personal_templates_can_be_default"})
