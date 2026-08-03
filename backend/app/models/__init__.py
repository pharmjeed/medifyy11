"""نماذج DOC-04 v1.1 (24 جدولاً) + طبقة المنصة (قرار مالك 2026-07-15: platform_admins, plans)
+ السجل المرجعي للأكواد registry_codes (قرار مالك 2026-08-02)
+ نظام البرومبتات (قرار مالك 2026-08-02: platform_default_prompts, doctor_templates)
+ مسار الملاحق Addendum (قرار مالك 2026-08-03 — CBAHI)
+ مسار Unlock للبوابة ① (قرار مالك 2026-08-03: note_unlocks)."""
from .base import Base
from .clinical import (
    Addendum,
    Approval,
    AudioChunk,
    DeliveryReceipt,
    EditEvent,
    GuidanceItem,
    NoteApproval,
    NoteUnlock,
    NoteVersion,
    Patient,
    PatientContextSnapshot,
    ProcessingAttempt,
    Recording,
    RetentionPolicy,
    Summary,
    SummarySection,
    Template,
    Transcript,
    UploadAttempt,
    UploadJob,
    Visit,
    VisitConsent,
)
from .platform import Plan, PlatformAdmin, PlatformAuditLog, PlatformDefaultPrompt, PlatformSetting
from .reference import RegistryCode
from .system import AuditLog, DailyMetric, MetricEvent, Notification
from .tenancy import (
    Clinic,
    CodingSystemConfig,
    DoctorTemplate,
    Facility,
    IntegrationConfig,
    Invoice,
    PasswordResetToken,
    SeatEvent,
    Subscription,
    User,
)

__all__ = [
    "Base",
    "Facility", "User", "Clinic", "Subscription", "SeatEvent", "Invoice",
    "PasswordResetToken", "IntegrationConfig", "CodingSystemConfig", "DoctorTemplate",
    "Patient", "PatientContextSnapshot", "Template", "Visit", "VisitConsent", "Recording",
    "Transcript", "Summary", "SummarySection", "GuidanceItem", "EditEvent",
    "NoteApproval", "NoteUnlock", "Approval", "UploadJob", "UploadAttempt", "Addendum",
    "AuditLog", "Notification",
    "PlatformAdmin", "Plan", "PlatformAuditLog", "PlatformDefaultPrompt", "PlatformSetting",
    "RegistryCode",
]
