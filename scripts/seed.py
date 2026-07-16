"""بذر بيانات تجريبية مطابقة للنموذج التفاعلي (CLAUDE-CODE-PROMPT §٢):
منشأتان (الثانية لاختبار العزل) · أدمن أ. سلطان الحربي · 5 دكاترة (منهم معطلة) ·
5 عيادات · 20 مريضاً «متزامناً» · 5 قوالب · 11 زيارة بحالات متنوعة.

يعمل بدور المالك (يتجاوز RLS — يحاكي خدمة المزامنة). idempotent: يتخطى المنشأة الموجودة.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import (  # noqa: E402
    Approval, AuditLog, Clinic, CodingSystemConfig, Facility, GuidanceItem,
    IntegrationConfig, Invoice, Notification, Patient, PatientContextSnapshot,
    Recording, SeatEvent, Subscription, Summary, SummarySection, Template,
    Transcript, UploadAttempt, UploadJob, User, Visit,
)
from app.pipelines.stt import MOCK_DIALOGUE  # noqa: E402
from app.security import hash_password  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.replace(hour=6, minute=0, second=0, microsecond=0)

ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "Admin@12345")
DOCTOR_PASSWORD = os.environ.get("SEED_DOCTOR_PASSWORD", "Doctor@12345")
# لا كلمة مرور افتراضية للسوبر أدمن — يُنشأ فقط إن ضُبطت صراحة (أمان الإنتاج).
# للتطوير: صدّر SEED_SUPER_ADMIN_PASSWORD (compose يمرّر Owner@12345 افتراضياً). للإنتاج: scripts/create_super_admin.py.
SUPER_ADMIN_PASSWORD = os.environ.get("SEED_SUPER_ADMIN_PASSWORD", "")


def d(days: int = 0, hour: int = 9, minute: int = 0) -> dt.datetime:
    return (TODAY - dt.timedelta(days=days)).replace(hour=hour, minute=minute)


SOAP4 = {"sections": [
    {"section_key": "S", "title": "الذاتي — Subjective", "instructions": "Summarize the patient's complaints, timeline, and adherence in the patient's voice."},
    {"section_key": "O", "title": "الموضوعي — Objective", "instructions": "Record vital signs and focused examination findings stated by the clinician."},
    {"section_key": "A", "title": "التقييم — Assessment", "instructions": "Document the clinician's stated assessment only — no inferred diagnoses."},
    {"section_key": "P", "title": "الخطة — Plan", "instructions": "List medications, investigations, monitoring, and follow-up interval as stated."},
]}
SOAP5_FIRST = {"sections": SOAP4["sections"] + [
    {"section_key": "H", "title": "التاريخ المرضي — History", "instructions": "Capture relevant past medical, family, and social history mentioned during the first visit."},
]}
SOAP5_E = {"sections": SOAP4["sections"] + [
    {"section_key": "E", "title": "تثقيف المريض — Patient education", "instructions": "One line of patient-directed education and safety-net advice."},
]}

# نص ملخص زيارة المراجعة VIS-8F42 — حرفياً من النموذج
SOAP0 = {
    "S": "58-year-old male with type 2 diabetes and hypertension presenting with morning headaches and mild dizziness for the past two weeks. Reports occasionally missing amlodipine doses; adherent to metformin. Home BP reading of approximately 155/95. Denies chest pain, visual disturbances, or focal weakness.",
    "O": "BP 150/95 mmHg, HR 78 bpm regular. Alert, oriented, in no acute distress. No focal neurological deficits on screening exam. Fundoscopy: [Not discussed].",
    "A": "1. Uncontrolled essential hypertension, likely contributed by partial medication non-adherence.\n2. Type 2 diabetes mellitus — control pending updated HbA1c (last 8.2%, April 2026).",
    "P": "Increase amlodipine 5 mg to 10 mg once daily. Order HbA1c and lipid panel. Medication adherence counseling provided. Follow-up in 2 weeks; return sooner if severe headache, chest pain, or neurological symptoms. Home BP monitoring twice daily with logged readings.",
    "E": "Counseled on the importance of daily amlodipine adherence. Advised low-salt diet and keeping a written log of home BP readings.",
}

# زيارة منيرة المعتمدة VIS-7C15 — حرفياً من النموذج (W-221)
SOAP_MUNIRA = {
    "S": "34-year-old female presenting with sore throat and low-grade fever for 3 days. Mild odynophagia, no cough, no shortness of breath. No sick contacts reported.",
    "O": "T 37.8°C, HR 84, BP 118/74. Erythematous pharynx without exudate. No cervical lymphadenopathy. Chest clear.",
    "A": "Acute pharyngitis, most likely viral.",
    "P": "Symptomatic treatment: paracetamol 500 mg PRN, warm fluids, rest. Return if symptoms persist beyond 5 days or fever rises.",
}

PATIENTS_CORE = [
    ("1042376", "عبدالله محمد العتيبي", "1968-03-14", "ذكر"),
    ("1029841", "منيرة سعد الدوسري", "1992-07-22", "أنثى"),
    ("1051209", "سعود عبدالعزيز المطيري", "1985-01-09", "ذكر"),
    ("1063327", "الجوهرة خالد العنزي", "1981-11-02", "أنثى"),
    ("1017754", "ناصر حمد الشمري", "1964-05-30", "ذكر"),
]
PATIENTS_EXTRA = [
    ("1071203", "بدر سليمان الدخيل", "1975-02-11", "ذكر"),
    ("1072415", "هيا محمد القحطاني", "1990-08-19", "أنثى"),
    ("1073528", "تركي عبدالله الحربي", "1958-12-03", "ذكر"),
    ("1074631", "لطيفة فهد العجمي", "1987-04-27", "أنثى"),
    ("1075744", "مشعل سعد الرشيدي", "1979-09-15", "ذكر"),
    ("1076857", "نوف خالد السبيعي", "1995-06-08", "أنثى"),
    ("1077960", "عبدالعزيز ناصر الزهراني", "1969-10-21", "ذكر"),
    ("1078073", "شهد إبراهيم الغانم", "1998-01-30", "أنثى"),
    ("1079186", "سلمان يوسف البقمي", "1983-03-17", "ذكر"),
    ("1080299", "العنود سلطان المالكي", "1991-12-25", "أنثى"),
    ("1081302", "فيصل حمد الدوسري", "1972-07-04", "ذكر"),
    ("1082415", "غادة عبدالرحمن الشهراني", "1986-05-13", "أنثى"),
    ("1083528", "ماجد فهد العنزي", "1961-08-28", "ذكر"),
    ("1084631", "ريما صالح القرني", "1993-02-06", "أنثى"),
    ("1085744", "خالد مساعد العصيمي", "1977-11-11", "ذكر"),
]


def seed_platform(db: Session) -> None:
    """طبقة المنصة (قرار مالك 2026-07-15): سوبر أدمن تطويري + التأكد من الباقتين — idempotent."""
    from decimal import Decimal

    from app.models import Plan, PlatformAdmin

    if not SUPER_ADMIN_PASSWORD:
        # لا حساب سوبر أدمن افتراضي — على الإنتاج يُنشأ عبر scripts/create_super_admin.py بكلمة قوية
        print("seed: تخطّي السوبر أدمن — اضبط SEED_SUPER_ADMIN_PASSWORD أو استخدم scripts/create_super_admin.py")
    elif not db.execute(select(PlatformAdmin).where(PlatformAdmin.username == "owner")).scalar_one_or_none():
        db.add(PlatformAdmin(
            username="owner",
            full_name="مالك ميديفاي",
            email="owner@medify.example.sa",
            password_hash=hash_password(SUPER_ADMIN_PASSWORD),
            role="owner",  # الدرجة العليا — DOC-20 §١.٢
            is_active=True,
        ))
        print("seed: أُنشئ السوبر أدمن التطويري owner")
    for code, name_ar, name_en, price, cycle in [
        ("monthly", "شهرية", "Monthly", Decimal("400.00"), "monthly"),
        ("yearly", "سنوية", "Yearly", Decimal("4080.00"), "yearly"),
    ]:
        if not db.execute(select(Plan).where(Plan.code == code)).scalar_one_or_none():
            db.add(Plan(code=code, name_ar=name_ar, name_en=name_en,
                        seat_price_sar=price, billing_cycle=cycle, is_active=True))
    db.flush()


def seed(db: Session) -> None:
    seed_platform(db)
    if db.execute(select(Facility).where(Facility.commercial_reg == "1010456789")).scalar_one_or_none():
        print("seed: المنشأة موجودة — تخطٍّ (idempotent)")
        return

    # ===== المنشأة 1: مجمع الشفاء الطبي =====
    facility = Facility(name="مجمع الشفاء الطبي", commercial_reg="1010456789", status="active")
    db.add(facility)
    db.flush()
    fid = facility.id

    admin = User(facility_id=fid, role="admin", full_name="سلطان عبدالله الحربي",
                 username="admin", email="sultan.alharbi@alshifa.example.sa",
                 password_hash=hash_password(ADMIN_PASSWORD), is_active=True)
    db.add(admin)
    db.flush()

    clinics = {}
    for name in ["عيادة الباطنة", "عيادة الأطفال", "عيادة الجلدية", "عيادة طب الأسرة", "عيادة التغذية"]:
        clinic = Clinic(facility_id=fid, name=name)
        if name == "عيادة التغذية":
            clinic.archived_at = d(20, 14, 0)
        db.add(clinic)
        db.flush()
        clinics[name] = clinic

    doctors = {}
    for username, full_name, specialty, clinic_name, active in [
        ("dr.ahmad", "أحمد سعد الغامدي", "باطنة", "عيادة الباطنة", True),
        ("dr.noura", "نورة فهد القحطاني", "أطفال", "عيادة الأطفال", True),
        ("dr.khaled", "خالد ناصر العتيبي", "جلدية", "عيادة الجلدية", True),
        ("dr.fahad", "فهد محمد السبيعي", "طب أسرة", "عيادة طب الأسرة", True),
        ("dr.reem", "ريم عبدالله الشهري", "باطنة", "عيادة الباطنة", False),
    ]:
        doctor = User(facility_id=fid, role="doctor", full_name=f"د. {full_name}", username=username,
                      password_hash=hash_password(DOCTOR_PASSWORD), specialty=specialty,
                      clinic_id=clinics[clinic_name].id, is_active=active,
                      email=f"{username.replace('.', '_')}@alshifa.example.sa")
        db.add(doctor)
        db.flush()
        doctors[username] = doctor
    ahmad = doctors["dr.ahmad"]

    subscription = Subscription(facility_id=fid, seats_total=6, plan="monthly", billing_ref="mock")
    db.add(subscription)
    db.flush()
    for delta, reason, days in [(3, "expand", 72), (1, "expand", 41), (0, "activate_dr", 43),
                                (0, "deactivate_dr", 27), (2, "expand", 14)]:
        event = SeatEvent(subscription_id=subscription.id, delta=delta, reason=reason, actor_user_id=admin.id)
        event.created_at = d(days, 10, 3)
        db.add(event)

    from decimal import Decimal
    for number, days, amount, status in [
        ("INV-2026-0388", 72, Decimal("1200.00"), "paid"),
        ("INV-2026-0512", 41, Decimal("1600.00"), "paid"),
        ("INV-2026-0641", 14, Decimal("2400.00"), "paid"),
        ("INV-2026-0713", 2, Decimal("2400.00"), "due"),
    ]:
        invoice = Invoice(
            facility_id=fid, subscription_id=subscription.id, number=number,
            period_start=d(days), period_end=d(days) + dt.timedelta(days=30),
            amount_sar=amount, vat_sar=(amount * Decimal("0.15")).quantize(Decimal("0.01")),
            status=status, issued_at=d(days, 9, 0),
            paid_at=d(days - 1, 11, 30) if status == "paid" else None,
        )
        db.add(invoice)

    for system in ("ICD10AM", "ACHI", "SBS", "SFDA"):
        db.add(CodingSystemConfig(facility_id=fid, system=system, version="2024", is_active=True))
    db.add(IntegrationConfig(facility_id=fid, endpoint_url="https://his.alshifa.example.sa/fhir",
                             auth_secret_encrypted="mock-secret", mode="test",
                             last_test_at=d(0, 8, 5), last_test_ok=True))

    patients = {}
    for mrn, name, dob, gender in PATIENTS_CORE + PATIENTS_EXTRA:
        patient = Patient(facility_id=fid, hospital_mrn=mrn, display_name=name,
                          dob=dob, gender=gender, synced_at=d(0, 8, 0))
        db.add(patient)
        db.flush()
        patients[mrn] = patient

    templates = {}
    for key, name, specialty, visit_type, structure, origin, owner in [
        ("r1", "باطنة — متابعة عامة SOAP", "باطنة", "متابعة", SOAP4, "system", None),
        ("r2", "باطنة — كشف أول", "باطنة", "كشف أول", SOAP5_FIRST, "system", None),
        ("r3", "أطفال — كشف عام", "أطفال", "كشف", SOAP4, "system", None),
        ("r4", "جلدية — استشارة", "جلدية", "استشارة", SOAP4, "system", None),
        ("pt1", "متابعة سكري وضغط — مختصر", "باطنة", "متابعة", SOAP5_E, "reverse_built", ahmad.id),
    ]:
        template = Template(facility_id=fid, owner_user_id=owner, name=name, specialty=specialty,
                            visit_type=visit_type, structure_json=structure, origin=origin,
                            is_default=(key == "pt1"),
                            source_sample_text="S: Follow-up of T2DM and HTN..." if key == "pt1" else None)
        db.add(template)
        db.flush()
        templates[key] = template

    baladona = clinics["عيادة الباطنة"]

    def make_visit(mrn: str, state: str, created: dt.datetime, template_key: str = "r1") -> Visit:
        patient = patients[mrn]
        snapshot = PatientContextSnapshot(
            patient_id=patient.id, facility_id=fid,
            content_json={
                "problems": ["Type 2 diabetes mellitus (2018)", "Essential hypertension (2020)"] if mrn == "1042376" else ["—"],
                "medications": ["Metformin 1000 mg BID", "Amlodipine 5 mg OD"] if mrn == "1042376" else [],
                "allergies": ["Penicillin"] if mrn == "1042376" else ["No known drug allergies"],
                "last_results": ["HbA1c 8.2% — 2026-04-02"] if mrn == "1042376" else [],
                "last_visit": "2026-05-12",
                "source": "hospital_sync",
            },
            fetched_at=created,
        )
        db.add(snapshot)
        db.flush()
        visit = Visit(facility_id=fid, clinic_id=baladona.id, doctor_id=ahmad.id,
                      patient_id=patient.id, template_id=templates[template_key].id,
                      state=state, context_snapshot_id=snapshot.id)
        visit.created_at = created
        db.add(visit)
        db.flush()
        return visit

    def add_transcript(visit: Visit) -> None:
        db.add(Transcript(visit_id=visit.id, facility_id=fid,
                          content_json={"segments": [
                              {"id": f"s-{i}", "text": text, "t0": i * 8.0, "t1": i * 8.0 + 6.5}
                              for i, text in enumerate(MOCK_DIALOGUE)
                          ]},
                          language_stats={"ar": 0.9, "en": 0.1}))
        db.add(Recording(visit_id=visit.id, facility_id=fid,
                         storage_uri=f"var/recordings/{visit.id}.opus", duration_sec=92,
                         retention_until=NOW + dt.timedelta(days=30)))

    def add_summary(visit: Visit, contents: dict[str, str], template_key: str = "pt1") -> dict[str, SummarySection]:
        summary = Summary(visit_id=visit.id, facility_id=fid,
                          model_ref="P2-summary@1.0/mock", generated_at=visit.created_at + dt.timedelta(minutes=2))
        db.add(summary)
        db.flush()
        sections = {}
        for index, section_def in enumerate(templates[template_key].structure_json["sections"]):
            key = section_def["section_key"]
            content = contents.get(key, "[Not discussed]")
            section = SummarySection(summary_id=summary.id, facility_id=fid, section_key=key,
                                     position=index, content_current=content, content_original=content)
            db.add(section)
            db.flush()
            sections[key] = section
        return sections

    def approve_and_upload(visit: Visit, ok: bool, days: int) -> None:
        approval = Approval(visit_id=visit.id, facility_id=fid, approved_by=ahmad.id,
                            approved_at=visit.created_at + dt.timedelta(minutes=6),
                            summary_hash="sha256:" + "1f6a09c2e"[:9] + str(visit.id)[:8],
                            codes_hash="sha256:" + "88d307b1"[:8] + str(visit.id)[:8])
        db.add(approval)
        db.flush()
        job = UploadJob(visit_id=visit.id, facility_id=fid,
                        fhir_payload_ref=f"var/fhir/{visit.id}.json",
                        status="confirmed" if ok else "failed",
                        attempts_count=1 if ok else 3)
        db.add(job)
        db.flush()
        if ok:
            db.add(UploadAttempt(job_id=job.id, started_at=approval.approved_at + dt.timedelta(minutes=1),
                                 result="confirmed", error_code=None))
        else:
            for attempt in range(3):
                db.add(UploadAttempt(job_id=job.id,
                                     started_at=approval.approved_at + dt.timedelta(minutes=1 + attempt * 5),
                                     result="failed", error_code="MDF-5052"))
        db.add(AuditLog(facility_id=fid, actor_user_id=ahmad.id, action="visit.approved",
                        entity="visit", entity_id=str(visit.id), meta_json=None, at=approval.approved_at))

    # 11 زيارة مطابقة لسجل النموذج (VIS-xxxx تجريبية — المعرف الحقيقي UUID)
    v_draft = make_visit("1063327", "draft", d(0, 11, 0), "r1")                 # VIS-8B03
    v_failed = make_visit("1017754", "approved", d(0, 10, 22), "r1")            # VIS-7A19
    add_transcript(v_failed); add_summary(v_failed, SOAP_MUNIRA, "r1")
    approve_and_upload(v_failed, ok=False, days=0)
    v_failed.state = "upload_failed"

    v_up1 = make_visit("1051209", "approved", d(0, 9, 45), "r1")                # VIS-8D07
    add_transcript(v_up1); add_summary(v_up1, SOAP_MUNIRA, "r1")
    approve_and_upload(v_up1, ok=True, days=0); v_up1.state = "uploaded"

    v_review = make_visit("1042376", "in_review", d(0, 9, 12), "pt1")           # VIS-8F42
    add_transcript(v_review)
    review_sections = add_summary(v_review, SOAP0, "pt1")
    guidance_data = [
        ("A", "coding_match", "ICD10AM", "I10", "Essential (primary) hypertension", "pending", False,
         "current_visit", "قياس العيادة 150/95", "التشخيص الأول موثّق كارتفاع ضغط أساسي غير منضبط — الصياغة مطابقة للتقييم."),
        ("A", "coding_match", "ICD10AM", "E11.9", "Type 2 diabetes mellitus without complication", "accepted", False,
         "patient_file", "تشخيص مسجل منذ 2018", "متابعة سكري نوع 2 دون مضاعفات موثقة في هذه الزيارة."),
        ("A", "clinical_dx", "ICD10AM", "G43.9", "Consider migraine as differential for recurrent morning headache", "rejected", False,
         "current_visit", "«صداع خصوصاً الصبح»", "صداع صباحي متكرر — قُدّم كتشخيص تفريقي، والأرجح سريرياً أنه ثانوي لارتفاع الضغط."),
        ("P", "clinical_rx", None, None,
         "Amlodipine 10 mg is the maximum recommended dose — counsel on peripheral edema and reassess within 2 weeks.",
         "pending", True, "current_visit", "قرار رفع الجرعة في الخطة",
         "رفع الجرعة إلى الحد الأقصى لدى مريض 58 عاماً يستلزم توثيق التثقيف والمتابعة. فحص التعارض: لا تعارض مع Metformin، والحساسية المسجلة (Penicillin) لا تمس الخطة."),
        ("P", "coding_match", "ACHI", "66551-00", "Glycated haemoglobin (HbA1c) — pathology order", "pending", False,
         "current_visit", "«نطلب تحليل التراكمي والدهون»", "طلب تحليل التراكمي يتطلب رمز إجراء مخبرياً مطابقاً قبل الرفع."),
        ("P", "coding_match", "SFDA", "GTIN 6285074001122", "Amlodipine besylate 10 mg tablet", "accepted", False,
         "current_visit", "الخطة الدوائية المعدلة", "توحيد وصف الدواء برمز سجل SFDA المعتمد لدى المنشأة."),
    ]
    for key, kind, code_system, code_value, text, status, safety, source, ref, rationale in guidance_data:
        item = GuidanceItem(section_id=review_sections[key].id, facility_id=fid, kind=kind,
                            suggestion_text=text, code_system=code_system, code_value=code_value,
                            evidence_source=source,
                            evidence_ref={"ref": ref, "rationale": rationale, "safety_flag": safety},
                            status=status)
        if status != "pending":
            item.resolved_by = ahmad.id
            item.resolved_at = v_review.created_at + dt.timedelta(minutes=4)
        db.add(item)

    v_munira = make_visit("1029841", "approved", d(1, 11, 38), "r1")            # VIS-7C15
    add_transcript(v_munira)
    munira_sections = add_summary(v_munira, SOAP_MUNIRA, "r1")
    db.add(GuidanceItem(section_id=munira_sections["A"].id, facility_id=fid, kind="coding_match",
                        suggestion_text="Acute pharyngitis, unspecified", code_system="ICD10AM",
                        code_value="J02.9", evidence_source="current_visit",
                        evidence_ref={"ref": "sore throat and fever for 3 days", "safety_flag": False},
                        status="accepted", resolved_by=ahmad.id, resolved_at=d(1, 11, 40)))
    approve_and_upload(v_munira, ok=True, days=1); v_munira.state = "uploaded"

    for mrn, days, hour, minute in [("1063327", 1, 9, 47), ("1042376", 13, 12, 5),
                                    ("1017754", 15, 10, 50), ("1063327", 21, 9, 5)]:
        visit = make_visit(mrn, "approved", d(days, hour, minute), "r1")
        add_transcript(visit); add_summary(visit, SOAP_MUNIRA, "r1")
        approve_and_upload(visit, ok=True, days=days); visit.state = "uploaded"

    v_summarized = make_visit("1029841", "summarized", d(17, 13, 20), "r1")     # VIS-6C77
    add_transcript(v_summarized); add_summary(v_summarized, SOAP_MUNIRA, "r1")

    v_cancelled = make_visit("1051209", "cancelled", d(23, 10, 15), "r1")       # VIS-6B12

    # إشعارات النموذج (W-003)
    for user, kind, payload, days, read in [
        (ahmad, "dr.safety_flag", {"visit_id": str(v_review.id)}, 0, False),
        (ahmad, "dr.summary_ready", {"visit_id": str(v_review.id)}, 0, True),
        (ahmad, "dr.upload_failed", {"visit_id": str(v_failed.id), "mdf": "MDF-5052"}, 0, False),
        (admin, "ad.integration_down", {"mdf": "MDF-5052"}, 1, False),
        (admin, "ad.upload_failed", {"visit_id": str(v_failed.id), "mdf": "MDF-5052"}, 0, False),
        (admin, "ad.renewal_upcoming", {"days_left": 14}, 2, True),
    ]:
        notification = Notification(facility_id=fid, user_id=user.id, kind=kind, payload_json=payload,
                                    read_at=d(days, 12, 0) if read else None)
        notification.created_at = d(days, 10, 31)
        db.add(notification)

    # سجل تدقيق تمهيدي
    for action, entity, days, actor in [
        ("integration.tested", "integration_configs", 0, admin),
        ("visit.approved", "visit", 1, ahmad),
        ("doctor.created", "users", 13, admin),
        ("subscription.seats_changed", "seat_events", 14, admin),
        ("doctor.password_reset", "users", 17, admin),
        ("coding_systems.updated", "coding_system_configs", 20, admin),
        ("template.created", "templates", 25, admin),
        ("doctor.updated", "users", 27, admin),
    ]:
        db.add(AuditLog(facility_id=fid, actor_user_id=actor.id, action=action, entity=entity,
                        entity_id=None, meta_json=None, at=d(days, 10, 0)))

    # ===== المنشأة 2 — لاختبار العزل =====
    facility2 = Facility(name="مستشفى النخبة التخصصي", commercial_reg="2020987654", status="active")
    db.add(facility2)
    db.flush()
    admin2 = User(facility_id=facility2.id, role="admin", full_name="ماجد عبدالله العمري",
                  username="admin", email="majed@alnukhba.example.sa",
                  password_hash=hash_password(ADMIN_PASSWORD), is_active=True)
    db.add(admin2)
    clinic2 = Clinic(facility_id=facility2.id, name="عيادة القلب")
    db.add(clinic2)
    db.flush()
    doctor2 = User(facility_id=facility2.id, role="doctor", full_name="د. سالم راشد الدوسري",
                   username="dr.salem", password_hash=hash_password(DOCTOR_PASSWORD),
                   specialty="قلب", clinic_id=clinic2.id, is_active=True,
                   email="dr_salem@alnukhba.example.sa")
    db.add(doctor2)
    subscription2 = Subscription(facility_id=facility2.id, seats_total=3, plan="monthly")
    db.add(subscription2)
    db.flush()
    for system in ("ICD10AM", "ACHI", "SBS", "SFDA"):
        db.add(CodingSystemConfig(facility_id=facility2.id, system=system, version="2024", is_active=True))
    db.add(IntegrationConfig(facility_id=facility2.id, mode="test"))
    patient2 = Patient(facility_id=facility2.id, hospital_mrn="2201001", display_name="حصة فيصل السديري",
                       dob="1970-01-01", gender="أنثى", synced_at=NOW)
    db.add(patient2)
    template2 = Template(facility_id=facility2.id, owner_user_id=None, name="قلب — متابعة",
                         specialty="قلب", visit_type="متابعة", structure_json=SOAP4, origin="system")
    db.add(template2)
    db.flush()
    snapshot2 = PatientContextSnapshot(patient_id=patient2.id, facility_id=facility2.id,
                                       content_json={"problems": []}, fetched_at=NOW)
    db.add(snapshot2)
    db.flush()
    db.add(Visit(facility_id=facility2.id, clinic_id=clinic2.id, doctor_id=doctor2.id,
                 patient_id=patient2.id, template_id=template2.id, state="draft",
                 context_snapshot_id=snapshot2.id))

    print("seed: اكتمل — منشأتان، 6 مستخدمين + دكتور معزول، 21 مريضاً، 6 قوالب، 12 زيارة")


def main() -> None:
    settings = get_settings()
    url = os.environ.get("MIGRATIONS_DATABASE_URL") or settings.migrations_database_url or settings.database_url
    engine = create_engine(url)
    with Session(engine) as db:
        seed(db)
        db.commit()


if __name__ == "__main__":
    main()
