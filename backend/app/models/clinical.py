"""جداول المرضى والقوالب والزيارة — DOC-04 §٤/§٥."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..crypto import EncryptedJSON, EncryptedText
from .base import Base, TimestampMixin, pk

TEMPLATE_ORIGIN = Enum("system", "reverse_built", name="template_origin")
VISIT_STATE = Enum(
    "draft", "recording", "transcribed", "summarized", "in_review",
    "approved", "uploaded", "upload_failed", "cancelled",
    name="visit_state",
)
GUIDANCE_KIND = Enum("clinical_dx", "clinical_rx", "clinical_procedure", "coding_match", name="guidance_kind")
EVIDENCE_SOURCE = Enum("patient_file", "current_visit", name="evidence_source")
GUIDANCE_STATUS = Enum("pending", "accepted", "rejected", "modified", name="guidance_status")
EDIT_CHANNEL = Enum("typing", "voice", "ai_chat", name="edit_channel")
UPLOAD_STATUS = Enum("queued", "sent", "confirmed", "failed", name="upload_status")


class Patient(Base, TimestampMixin):
    """المرضى — بالمزامنة حصراً (قرار مالك 2026-07-14): لا API إنشاء/تعديل."""

    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("facility_id", "hospital_mrn", name="uq_patients_facility_mrn"),)

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    hospital_mrn: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(EncryptedText, nullable=False)  # PII
    dob: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)     # PII
    gender: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)  # PII
    synced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PatientContextSnapshot(Base, TimestampMixin):
    __tablename__ = "patient_context_snapshots"

    id: Mapped[uuid.UUID] = pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    content_json: Mapped[Any] = mapped_column(EncryptedJSON, nullable=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Template(Base, TimestampMixin):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # null = عام
    name: Mapped[str] = mapped_column(Text, nullable=False)
    specialty: Mapped[str | None] = mapped_column(Text, nullable=True)
    visit_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    structure_json: Mapped[Any] = mapped_column(JSONB, nullable=False)  # {sections:[{section_key,title,instructions}]}
    origin: Mapped[str] = mapped_column(TEMPLATE_ORIGIN, nullable=False, default="system")
    source_sample_text: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Visit(Base, TimestampMixin):
    __tablename__ = "visits"

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("templates.id"), nullable=False)
    state: Mapped[str] = mapped_column(VISIT_STATE, nullable=False, default="draft")
    context_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("patient_context_snapshots.id"), nullable=True
    )


class Recording(Base, TimestampMixin):
    __tablename__ = "recordings"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), unique=True, nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retention_until: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Transcript(Base, TimestampMixin):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), unique=True, nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    content_json: Mapped[Any] = mapped_column(EncryptedJSON, nullable=False)  # segments بطوابع زمنية
    language_stats: Mapped[Any | None] = mapped_column(JSONB, nullable=True)


class Summary(Base, TimestampMixin):
    __tablename__ = "summaries"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), unique=True, nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    model_ref: Mapped[str] = mapped_column(Text, nullable=False)  # {pipeline, prompt_version, model} — DOC-14
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SummarySection(Base, TimestampMixin):
    __tablename__ = "summary_sections"

    id: Mapped[uuid.UUID] = pk()
    summary_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("summaries.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    section_key: Mapped[str] = mapped_column(Text, nullable=False)  # S|O|A|P|custom (من القالب ديناميكياً)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content_current: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    content_original: Mapped[str] = mapped_column(EncryptedText, nullable=False)


class GuidanceItem(Base, TimestampMixin):
    __tablename__ = "guidance_items"

    id: Mapped[uuid.UUID] = pk()
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("summary_sections.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(GUIDANCE_KIND, nullable=False)
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    code_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_source: Mapped[str] = mapped_column(EVIDENCE_SOURCE, nullable=False)
    evidence_ref: Mapped[Any] = mapped_column(JSONB, nullable=False)  # {ref, excerpt?, safety_flag}
    status: Mapped[str] = mapped_column(GUIDANCE_STATUS, nullable=False, default="pending")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EditEvent(Base, TimestampMixin):
    __tablename__ = "edit_events"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("summary_sections.id"), nullable=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(EDIT_CHANNEL, nullable=False)
    payload_json: Mapped[Any] = mapped_column(EncryptedJSON, nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)


class Approval(Base, TimestampMixin):
    """إلحاقي فقط — لا UPDATE/DELETE (REVOKE + trigger). بصمة ما اعتُمد (NFR-10)."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), unique=True, nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary_hash: Mapped[str] = mapped_column(Text, nullable=False)
    codes_hash: Mapped[str] = mapped_column(Text, nullable=False)


class UploadJob(Base, TimestampMixin):
    """لا يُنشأ صف إلا بوجود approval — FK إلى approvals.visit_id يفرض FR-803 على مستوى القاعدة."""

    __tablename__ = "upload_jobs"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approvals.visit_id"), unique=True, nullable=False
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    fhir_payload_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(UPLOAD_STATUS, nullable=False, default="queued")
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UploadAttempt(Base, TimestampMixin):
    __tablename__ = "upload_attempts"

    id: Mapped[uuid.UUID] = pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload_jobs.id"), nullable=False, index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # confirmed | failed
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)  # رموز DOC-13
