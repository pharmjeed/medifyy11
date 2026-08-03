"""جداول المرضى والقوالب والزيارة — DOC-04 §٤/§٥."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
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
    "approved", "uploaded", "upload_failed", "cancelled", "voided",
    name="visit_state",
)
# توجيه المالك 2026-07-22: كل بند خطة كيان مهيكل بكوده — أُضيف نوعا الخدمة والجهاز
GUIDANCE_KIND = Enum(
    "clinical_dx", "clinical_rx", "clinical_procedure", "coding_match",
    "clinical_service", "clinical_device",
    name="guidance_kind",
)
CONSENT_METHOD = Enum("verbal_ack", "written", name="consent_method")
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
    # برومبتات (FR-500+)
    prompt_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # محتوى البرومبت الفعلي
    prompt_source: Mapped[str] = mapped_column(Text, nullable=False, default="default")  # default أو custom
    prompt_template_type: Mapped[str | None] = mapped_column(Text, nullable=True)  # ربط بـ platform_default_prompts


class Visit(Base, TimestampMixin):
    __tablename__ = "visits"

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("templates.id"), nullable=False)
    state: Mapped[str] = mapped_column(VISIT_STATE, nullable=False, default="draft")
    # دورة النسخ (م6): يرتفع مع كل reopen — بوابتا كل نسخة مستقلتان (triggers 0014)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # م8: تجميد كل حذف احتفاظي لأثار الزيارة (تحقيق/نزاع) — لا يُحذف منها شيء وهو مرفوع
    legal_hold: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")
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


class AudioChunk(Base, TimestampMixin):
    """سجل مقاطع الصوت المتدفقة (المرحلة 2 من التحصين) — ترقيم عالمي معمَّر عبر الاتصالات.

    القيد الفريد (visit_id, chunk_index) يجعل إعادة رفع نفس المقطع idempotent:
    الخادم يعيد ack بلا كتابة — لا تكرار في WAV عند ضياع الإقرار. sha256 والإزاحة/الطول
    يتيحان تحقق finalize الصارم (لا-فجوات + bit-exact) قبل إطلاق P1.
    """

    __tablename__ = "audio_chunks"
    __table_args__ = (UniqueConstraint("visit_id", "chunk_index", name="uq_audio_chunks_visit_index"),)

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)  # إزاحة PCM (بلا ترويسة WAV)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessingAttempt(Base, TimestampMixin):
    """محاولة معالجة لمرحلة P1/P2/P3 (المرحلة 3 من التحصين) — سجل معمَّر بلا PHI.

    يُكتب بجلسة نظام مستقلة عن معاملة الطلب: الفشل النهائي يُرجِع rollback للطلب
    لكن سجل محاولاته يبقى (المرجع عند MDF-5031/5032 وتقرير processing-status).
    """

    __tablename__ = "processing_attempts"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)  # P1 | P2 | P3
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    error_class: Mapped[str] = mapped_column(Text, nullable=False)  # retryable | non_retryable | none
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    succeeded: Mapped[bool] = mapped_column(default=False, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VisitConsent(Base, TimestampMixin):
    """موافقة المريض الموثّقة — إلحاقي فقط. لا تسجيل قبلها (trigger القاعدة يرفض draft→recording)."""

    __tablename__ = "visit_consents"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), unique=True, nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    consent_version: Mapped[str] = mapped_column(Text, nullable=False)   # CONSENT-AR-EN@1.0
    consent_text_hash: Mapped[str] = mapped_column(Text, nullable=False)  # بصمة النص المعروض بالضبط
    method: Mapped[str] = mapped_column(CONSENT_METHOD, nullable=False, default="verbal_ack")
    captured_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)  # هوية الملتقط
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Transcript(Base, TimestampMixin):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), unique=True, nullable=False)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    content_json: Mapped[Any] = mapped_column(EncryptedJSON, nullable=False)  # segments بطوابع زمنية
    language_stats: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    # م8: مرحلة soft قبل الحذف الصلب (سماح 7 أيام) — transcript_raw=90 يوماً افتراضاً
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    # م10: السند جملةً بجملة — [{text, segment_ids, audio_start_ms, audio_end_ms, origin}]
    evidence_json: Mapped[Any | None] = mapped_column(EncryptedJSON, nullable=True)


class GuidanceItem(Base, TimestampMixin):
    """بند خطة مهيكل بكوده (توجيه المالك 2026-07-22):
    دواء SFDA+GTIN · إجراء ACHI+SBS · خدمة/مختبر/أشعة SBS · جهاز GMDN+GTIN بمبرر إلزامي.
    كل بند يحمل linked_dx_code لتشخيص ICD-10-AM، ودرجة ثقة مع إصدار السجل المرجعي وتاريخ سريانه.
    """

    __tablename__ = "guidance_items"
    __table_args__ = (
        # الجهاز بلا مبرر مرفوض على مستوى القاعدة
        CheckConstraint(
            "kind::text <> 'clinical_device' OR justification IS NOT NULL",
            name="ck_guidance_device_justification",
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("summary_sections.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(GUIDANCE_KIND, nullable=False)
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    code_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # الكود الثانوي: GTIN مع SFDA للدواء · SBS مع ACHI للإجراء · GTIN مع GMDN للجهاز
    code_secondary_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_secondary_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # provenance الكود — يُعرض كما ورد من السجل المرجعي بلا تحويل
    code_registry_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_effective_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    # دون العتبة: الكود يُحجب ويُعرض «يتطلب إدخال الطبيب» — لا تخمين
    requires_doctor_input: Mapped[bool] = mapped_column(default=False, nullable=False)
    linked_dx_code: Mapped[str | None] = mapped_column(Text, nullable=True)  # ICD-10-AM
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)   # إلزامي للجهاز
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


class NoteApproval(Base, TimestampMixin):
    """بوابة الاعتماد ① — اعتماد نص المذكرة. إلحاقي فقط.

    توجيه المالك 2026-07-22: بوابتان منفصلتان لا بوابة واحدة. الأكواد (②) لا تُعتمد إلا بعدها،
    ويُفرض ذلك بمفتاح أجنبي: approvals.note_approval_id → note_approvals.id (NOT NULL).
    مسار Unlock (قرار مالك 2026-08-03): الصف لا يُعدَّل ولا يُحذف؛ نقضه صف note_unlocks يشير إليه،
    وإعادة الاعتماد صف جديد — لذا visit_id فهرس لا UNIQUE، وtrigger القاعدة يضمن نشطاً واحداً قبل ②.
    """

    __tablename__ = "note_approvals"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")  # دورة النسخة (م6)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary_hash: Mapped[str] = mapped_column(Text, nullable=False)  # بصمة البوابة ①


class NoteUnlock(Base, TimestampMixin):
    """نقض اعتماد البوابة ① — مسار Unlock (قرار مالك 2026-08-03). إلحاقي فقط.

    حلقة CDI: مراجعة الأكواد (②) تكشف نقص توثيق (جهة الإصابة، مع/بدون مضاعفات…) والنص مجمّد —
    بدل اعتماد كود بلا سند أو كود أقل تحديداً: نقض بسبب مسجّل → تعديل → إعادة اعتماد ①.
    ممكن فقط قبل إتمام البوابة ② (trigger القاعدة يرفض بعدها — بعد الاعتماد النهائي المسار Addendum).
    السبب قد يحمل تفصيلاً سريرياً فيُخزَّن هنا مشفّراً — audit_logs يحمل المرجع لا النص.
    """

    __tablename__ = "note_unlocks"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    note_approval_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("note_approvals.id"), unique=True, nullable=False  # اعتماد واحد يُنقض مرة واحدة
    )
    reason: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    unlocked_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    unlocked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Approval(Base, TimestampMixin):
    """بوابة الاعتماد ② — اعتماد الأكواد. إلحاقي فقط (REVOKE + trigger). بصمة ما اعتُمد (NFR-10).

    لا تُنشأ إلا بوجود note_approval (①)، ولا رفع/تصدير إلا بوجودها هي (upload_jobs FK).
    م6: اعتماد واحد لكل دورة (visit_id, cycle) — كل نسخة reopen تعيد بوابتها ②.
    """

    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("visit_id", "cycle", name="uq_approvals_visit_cycle"),)

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    note_approval_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("note_approvals.id"), nullable=False
    )
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary_hash: Mapped[str] = mapped_column(Text, nullable=False)
    codes_hash: Mapped[str] = mapped_column(Text, nullable=False)  # بصمة البوابة ②


class UploadJob(Base, TimestampMixin):
    """لا يُنشأ صف إلا بوجود approval — FK إلى approvals.id يفرض FR-803 على مستوى القاعدة.

    م6: مهمة رفع لكل نسخة (approval_id UNIQUE) — retry-upload يعيد نفس المهمة/النسخة
    بلا بوابات (عطل تقني)، بينما reopen نسخة واعتماد ومهمة جديدة (قرار سريري).
    """

    __tablename__ = "upload_jobs"
    __table_args__ = (
        UniqueConstraint("approval_id", name="uq_upload_jobs_approval"),
        UniqueConstraint("idempotency_key", name="uq_upload_jobs_idempotency"),
    )

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approvals.id"), nullable=False)
    # م7: "{visit_id}:{version}" — الـretry بنفس المفتاح، والنسخة الجديدة مفتاح جديد
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    fhir_payload_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(UPLOAD_STATUS, nullable=False, default="queued")
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class NoteVersion(Base, TimestampMixin):
    """لقطة نسخة معتمدة (م6) — المبدأ 3: المنقولة immutable (trigger القاعدة يرفض أي UPDATE).

    تُنشأ مكتملة لحظة اعتماد البوابة ② (نص الأقسام + الأكواد المعتمدة + بصمة الحزمة
    + طوابع البوابتين)، وتتحدث حالتها حتى `uploaded` فتتجمد للأبد. reopen لا يمسها —
    ينشئ دورة جديدة تنتهي بصف نسخة جديد. diff عن السابقة يُخزن هنا مشفراً (محتوى
    سريري) — audit_logs يحمل الأعداد فقط.
    """

    __tablename__ = "note_versions"
    __table_args__ = (UniqueConstraint("visit_id", "version_number", name="uq_note_versions_visit_number"),)

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # {sections: [{section_key, position, content}]} — عند reopen نسخة من السابقة (مسودة)
    # ثم تُستبدل بالنص المعتمد حرفياً لحظة البوابة ②
    note_snapshot: Mapped[Any] = mapped_column(EncryptedJSON, nullable=False)
    # الأكواد المعتمدة (accepted|modified) بأنظمتها وربط تشخيصها ونصها
    approved_codes_snapshot: Mapped[Any] = mapped_column(EncryptedJSON, nullable=False)
    # حقول الاعتماد تكتمل عند البوابة ② — المسودة (draft) قبلها بلا بصمة ولا طوابع
    bundle_hash: Mapped[str | None] = mapped_column(Text, nullable=True)  # sha256 لحزمة FHIR الكاملة
    note_approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note_approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    codes_approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    codes_approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upload_status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")  # draft|pending|uploaded|upload_failed
    # سبب إعادة الفتح الذي أنتج هذه النسخة (v≥2) — محتوى سريري محتمل، مشفر
    reopen_reason: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    # diff نصي + أكواد عن النسخة السابقة (v≥2) — {sections: [...], codes: {...}, counts: {...}}
    diff_json: Mapped[Any | None] = mapped_column(EncryptedJSON, nullable=True)


class UploadAttempt(Base, TimestampMixin):
    __tablename__ = "upload_attempts"

    id: Mapped[uuid.UUID] = pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload_jobs.id"), nullable=False, index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # confirmed | failed
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)  # رموز DOC-13


class RetentionPolicy(Base, TimestampMixin):
    """تجاوز احتفاظ لكل منشأة (م8) — الافتراضات مضمّنة في services/retention.DEFAULTS.

    retention_days = NULL يعني «بلا حذف» لهذا النوع. legal_hold على الزيارة يتقدم
    على كل سياسة. الأدمن يعدّل سياسات منشأته من /settings/retention.
    """

    __tablename__ = "retention_policies"
    __table_args__ = (UniqueConstraint("facility_id", "artifact_type", name="uq_retention_facility_artifact"),)

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class DeliveryReceipt(Base, TimestampMixin):
    """إيصال تسليم لنظام المستشفى (م7) — كل استقبال ناجح يكتب إيصاله فوراً.

    الفحص قبل أي إرسال: إيصال قائم بنفس (المفتاح، الوجهة) = النجاح السابق يُرجَع
    بلا إرسال — انهيار بعد الإيصال وقبل تحديث المهمة لا يسبب كتابة مزدوجة في HIS.
    الكتابة بجلسة نظام مستقلة (commit فوري) والقيد الفريد صمام الأمان الأخير.
    """

    __tablename__ = "delivery_receipts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", "target_system", name="uq_delivery_receipts_key_target"),
    )

    id: Mapped[uuid.UUID] = pk()
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    target_system: Mapped[str] = mapped_column(Text, nullable=False)  # mock | http | hl7
    delivered_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response_hash: Mapped[str] = mapped_column(Text, nullable=False)  # بصمة ردّ الوجهة — لا محتوى


class Addendum(Base, TimestampMixin):
    """ملحق على مذكرة معتمدة نهائياً (قرار مالك 2026-08-03 — CBAHI).

    الملحق مرتبط بزيارة معتمدة، يحصل على طابعه الزمني ونصه الخاص، ويمر بوابة ① مصغّرة (review)
    ويحتمل بوابة ② مصغّرة إن غيّر الأكواد. الأصل يبقى كما هو حرفياً. عند التصدير: الأصل + الملاحق
    بالترتيب الزمني، كلٌّ موسوم. FHIR: Composition.status = "amended" مع relatesTo.
    """

    __tablename__ = "addendums"

    id: Mapped[uuid.UUID] = pk()
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visits.id"), nullable=False, index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # محتوى الملحق — بنية أقسام مثل الملخص الأصلي: {sections: [{section_key, content}]}
    content_json: Mapped[Any] = mapped_column(EncryptedJSON, nullable=False)
    # موافقة النص (بوابة ① مصغّرة)
    note_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("note_approvals.id"), nullable=True
    )
    # موافقة الأكواد (بوابة ② مصغّرة) — اختياري إن لم يكن في الملحق أكواد جديدة
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approvals.id"), nullable=True
    )
    # هل الملحق يتطلب موافقة؟ (pending) → approved بعد موافقة النص
    is_approved: Mapped[bool] = mapped_column(default=False, nullable=False)
