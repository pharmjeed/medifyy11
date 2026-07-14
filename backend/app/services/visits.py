"""خدمات الزيارة — الانتقالات عبر آلة الحالات (trigger القاعدة هو الحكم النهائي)."""
from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from ..errors import MedifyError
from ..models import GuidanceItem, Summary, SummarySection, Visit


def transition(db: Session, visit: Visit, new_state: str) -> None:
    """تحديث الحالة — أي انتقال ممنوع يرفضه trigger القاعدة → MDF-4223."""
    visit_id = str(visit.id)  # قبل flush — rollback يفقد سياق RLS للمعاملة (SET LOCAL)
    visit.state = new_state
    try:
        db.flush()
    except (IntegrityError, DBAPIError) as exc:
        message = str(exc.orig or exc)
        db.rollback()
        if "MDF-4223" in message:
            raise MedifyError("MDF-4223", details={"visit_id": visit_id, "to": new_state}) from exc
        raise


def get_visit_for_doctor(db: Session, visit_id: uuid.UUID) -> Visit:
    """RLS يضمن أن الدكتور لا يرى غير زياراته — الغياب = MDF-4041 (لا كشف عن الوجود)."""
    visit = db.execute(select(Visit).where(Visit.id == visit_id)).scalar_one_or_none()
    if visit is None:
        raise MedifyError("MDF-4041")
    return visit


def summary_etag(db: Session, visit: Visit) -> str:
    """ETag من بصمة محتوى الأقسام وحالات الإرشادات (D-13)."""
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    if summary is None:
        return "empty"
    hasher = hashlib.sha256()
    sections = db.execute(
        select(SummarySection)
        .where(SummarySection.summary_id == summary.id)
        .order_by(SummarySection.position)
    ).scalars().all()
    for section in sections:
        hasher.update(section.section_key.encode())
        hasher.update(section.content_current.encode())
        items = db.execute(
            select(GuidanceItem).where(GuidanceItem.section_id == section.id).order_by(GuidanceItem.id)
        ).scalars().all()
        for item in items:
            hasher.update(f"{item.id}:{item.status}:{item.suggestion_text}:{item.code_value}".encode())
    return hasher.hexdigest()[:32]


def summary_hashes(db: Session, visit: Visit) -> tuple[str, str]:
    """بصمة ما اعتُمد بالضبط — approvals (NFR-10)."""
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one()
    sections = db.execute(
        select(SummarySection)
        .where(SummarySection.summary_id == summary.id)
        .order_by(SummarySection.position)
    ).scalars().all()
    content_hasher = hashlib.sha256()
    codes_hasher = hashlib.sha256()
    for section in sections:
        content_hasher.update(f"{section.section_key}\n{section.content_current}\n".encode())
        items = db.execute(
            select(GuidanceItem).where(
                GuidanceItem.section_id == section.id,
                GuidanceItem.status.in_(["accepted", "modified"]),
            ).order_by(GuidanceItem.id)
        ).scalars().all()
        for item in items:
            codes_hasher.update(f"{item.code_system}:{item.code_value}:{item.suggestion_text}\n".encode())
    return content_hasher.hexdigest(), codes_hasher.hexdigest()
