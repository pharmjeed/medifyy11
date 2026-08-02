"""نماذج DOC-04 v1.1 (24 جدولاً) + طبقة المنصة (قرار مالك 2026-07-15: platform_admins, plans)
+ السجل المرجعي للأكواد registry_codes (قرار مالك 2026-08-02)
+ نظام البرومبتات (قرار مالك 2026-08-02: platform_default_prompts, doctor_templates)."""
from .base import Base
from .clinical import (
    Approval,
    EditEvent,
    GuidanceItem,
    NoteApproval,
    Patient,
    PatientContextSnapshot,
    Recording,
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
from .system import AuditLog, Notification
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
    "NoteApproval", "Approval", "UploadJob", "UploadAttempt",
    "AuditLog", "Notification",
    "PlatformAdmin", "Plan", "PlatformAuditLog", "PlatformDefaultPrompt", "PlatformSetting",
    "RegistryCode",
]
