"""مخرجات يوم-واحد (A3 — توجيه المالك 2026-07-22): وضع الجسر قبل اكتمال التكامل.

- `note_text`  : نص نظيف يُلصق مباشرة في الـ EMR.
- `note_pdf`   : PDF بترويسة وتذييل ثنائيي اللغة يعتمدان خط الهوية نفسه.

المخرجان لا يُتاحان إلا بعد البوابة ② (يفرضه المسار في api/v1/export.py).
"""
from __future__ import annotations

import datetime as dt
import io
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Approval,
    Clinic,
    Facility,
    GuidanceItem,
    NoteApproval,
    Patient,
    Summary,
    SummarySection,
    User,
    Visit,
)

# عناوين الأقسام كما تعرضها الواجهة — مصدر واحد للتسمية في كل المخرجات
SECTION_TITLES: dict[str, tuple[str, str]] = {
    "S": ("الشكوى والتاريخ", "Subjective"),
    "O": ("الفحص والعلامات", "Objective"),
    "A": ("التقييم", "Assessment"),
    "P": ("الخطة", "Plan"),
    "E": ("تثقيف المريض", "Patient education"),
}

KIND_LABEL: dict[str, tuple[str, str]] = {
    "clinical_dx": ("تشخيص", "Diagnosis"),
    "clinical_rx": ("دواء", "Medication"),
    "clinical_procedure": ("إجراء", "Procedure"),
    "clinical_service": ("خدمة/مختبر", "Service/Lab"),
    "clinical_device": ("جهاز", "Device"),
    "coding_match": ("مطابقة ترميز", "Coding match"),
}

_FONT_DIR = Path(__file__).resolve().parents[3] / "frontend" / "public" / "fonts"
_FONT_REGULAR = "MedifyPlexAr"
_FONT_BOLD = "MedifyPlexAr-Bold"


class ExportBundle:
    """كل ما تحتاجه المخرجات مجموعاً بنداء واحد على القاعدة."""

    def __init__(self, db: Session, visit: Visit) -> None:
        self.visit = visit
        self.facility = db.execute(select(Facility).where(Facility.id == visit.facility_id)).scalar_one()
        self.patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one()
        self.doctor = db.execute(select(User).where(User.id == visit.doctor_id)).scalar_one()
        self.clinic = db.execute(select(Clinic).where(Clinic.id == visit.clinic_id)).scalar_one_or_none()
        self.summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one()
        self.sections = db.execute(
            select(SummarySection)
            .where(SummarySection.summary_id == self.summary.id)
            .order_by(SummarySection.position)
        ).scalars().all()
        self.note_approval = db.execute(
            select(NoteApproval).where(NoteApproval.visit_id == visit.id)
        ).scalar_one_or_none()
        self.approval = db.execute(
            select(Approval).where(Approval.visit_id == visit.id)
        ).scalar_one_or_none()
        self.codes: list[GuidanceItem] = []
        for section in self.sections:
            self.codes.extend(
                db.execute(
                    select(GuidanceItem)
                    .where(
                        GuidanceItem.section_id == section.id,
                        GuidanceItem.status.in_(["accepted", "modified"]),
                    )
                    .order_by(GuidanceItem.created_at)
                ).scalars().all()
            )

    def section_title(self, key: str) -> tuple[str, str]:
        return SECTION_TITLES.get(key, (key, key))


def _fmt(moment: dt.datetime | None) -> str:
    return moment.strftime("%Y-%m-%d %H:%M") if moment else "—"


def _code_of(item: GuidanceItem) -> str:
    """تمثيل نصي للكود المهيكل — الأساسي ثم الثانوي، أو تنبيه الحجب دون العتبة."""
    if item.requires_doctor_input and not item.code_value:
        return "[requires clinician input]"
    if not item.code_value:
        return "—"
    out = f"{item.code_system or '—'} {item.code_value}"
    if item.code_secondary_value:
        out += f" · {item.code_secondary_system or '—'} {item.code_secondary_value}"
    return out


# ===================== نص نظيف للـ EMR =====================

def note_text(db: Session, visit: Visit) -> str:
    """نص عادي بلا أي ترميز — «نسخ للـ EMR» (F-086)."""
    data = ExportBundle(db, visit)
    lines: list[str] = []
    lines.append(f"{data.facility.name}")
    lines.append("Clinical note — مذكرة سريرية")
    lines.append("")
    lines.append(f"Patient / المريض: {data.patient.display_name}    MRN: {data.patient.hospital_mrn}")
    lines.append(f"Clinician / الطبيب: {data.doctor.full_name}"
                 + (f" — {data.doctor.specialty}" if data.doctor.specialty else ""))
    if data.clinic is not None:
        lines.append(f"Clinic / العيادة: {data.clinic.name}")
    lines.append(f"Visit date / تاريخ الزيارة: {_fmt(data.summary.generated_at)}")
    lines.append(f"Visit ID: {data.visit.id}")
    lines.append("")
    lines.append("-" * 68)

    for section in data.sections:
        title_ar, title_en = data.section_title(section.section_key)
        lines.append("")
        lines.append(f"{title_en.upper()} — {title_ar}")
        lines.append(section.content_current.strip())

    if data.codes:
        lines.append("")
        lines.append("-" * 68)
        lines.append("")
        lines.append("CODED ITEMS — البنود المرمّزة")
        for item in data.codes:
            label_ar, label_en = KIND_LABEL.get(item.kind, (item.kind, item.kind))
            row = f"  [{label_en}] {item.suggestion_text.strip()}"
            lines.append(row)
            detail = f"      code: {_code_of(item)}"
            if item.linked_dx_code:
                detail += f" · linked Dx: {item.linked_dx_code}"
            lines.append(detail)
            if item.justification:
                lines.append(f"      justification: {item.justification.strip()}")

    lines.append("")
    lines.append("-" * 68)
    if data.note_approval is not None:
        lines.append(f"Note approved (gate 1) / اعتماد النص: {_fmt(data.note_approval.approved_at)}"
                     f" · SHA-256 {data.note_approval.summary_hash[:16]}")
    if data.approval is not None:
        lines.append(f"Codes approved (gate 2) / اعتماد الأكواد: {_fmt(data.approval.approved_at)}"
                     f" · SHA-256 {data.approval.codes_hash[:16]}")
    lines.append("Reviewed and approved by the treating clinician — روجعت واعتُمدت من الطبيب المعالج.")
    return "\n".join(lines)


# ===================== PDF بترويسة ثنائية اللغة =====================

@lru_cache(maxsize=1)
def _register_fonts() -> bool:
    """يحوّل خطوط الهوية woff2 إلى TTF في الذاكرة ويسجّلها — لا ملفات خطوط مكررة في المستودع."""
    import io as _io

    from fontTools.ttLib import TTFont as _TTFont
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont as _RLFont

    pairs = [(_FONT_REGULAR, "ibm-plex-sans-arabic-400.woff2"),
             (_FONT_BOLD, "ibm-plex-sans-arabic-700.woff2")]
    for name, filename in pairs:
        path = _FONT_DIR / filename
        if not path.exists():
            return False
        font = _TTFont(str(path))
        font.flavor = None
        buffer = _io.BytesIO()
        font.save(buffer)
        buffer.seek(0)
        pdfmetrics.registerFont(_RLFont(name, buffer))
    return True


def _ar(text: str) -> str:
    """تشكيل العربية واتجاهها للرسم في PDF (reportlab لا يشكّل تلقائياً)."""
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.reshape(text))


def note_pdf(db: Session, visit: Visit) -> bytes:
    """مذكرة PDF بترويسة/تذييل ثنائيي اللغة (F-038/F-084)."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas

    data = ExportBundle(db, visit)
    fonts_ok = _register_fonts()
    regular = _FONT_REGULAR if fonts_ok else "Helvetica"
    bold = _FONT_BOLD if fonts_ok else "Helvetica-Bold"

    teal = HexColor("#0E7C86")
    teal_dark = HexColor("#0A5C64")
    gold = HexColor("#C9A227")
    ink = HexColor("#0F2233")
    muted = HexColor("#5B7280")
    line = HexColor("#D7E3E8")

    buffer = io.BytesIO()
    pdf = pdfcanvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left, right = 18 * mm, width - 18 * mm
    top = height - 16 * mm
    bottom_limit = 26 * mm
    state = {"page": 0, "y": 0.0}

    def arabic(text: str) -> str:
        return _ar(text) if fonts_ok else text

    def header() -> None:
        state["page"] += 1
        pdf.setFillColor(teal)
        pdf.setFont(bold, 15)
        pdf.drawRightString(right, top, arabic(data.facility.name))
        pdf.setFillColor(teal_dark)
        pdf.setFont(bold, 11)
        pdf.drawString(left, top, "Clinical Note")
        pdf.setFillColor(muted)
        pdf.setFont(regular, 8.5)
        pdf.drawRightString(right, top - 5.2 * mm, arabic("مذكرة سريرية معتمدة"))
        pdf.drawString(left, top - 5.2 * mm, f"Visit {str(data.visit.id)[:8]}")
        pdf.setStrokeColor(gold)
        pdf.setLineWidth(1.6)
        pdf.line(left, top - 8 * mm, right, top - 8 * mm)
        state["y"] = top - 15 * mm

    def footer() -> None:
        pdf.setStrokeColor(line)
        pdf.setLineWidth(0.6)
        pdf.line(left, 18 * mm, right, 18 * mm)
        pdf.setFillColor(muted)
        pdf.setFont(regular, 7.5)
        pdf.drawString(left, 13.5 * mm, "Generated by Medify — reviewed and approved by the treating clinician")
        pdf.drawRightString(right, 13.5 * mm, arabic("أُنتجت عبر Medify — روجعت واعتُمدت من الطبيب المعالج"))
        pdf.setFont(regular, 7.5)
        pdf.drawCentredString(width / 2, 9.5 * mm, f"{state['page']}")

    def ensure(space: float) -> None:
        if state["y"] - space < bottom_limit:
            footer()
            pdf.showPage()
            header()

    def wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        out: list[str] = []
        for paragraph in text.replace("\r", "").split("\n"):
            words = paragraph.split()
            if not words:
                out.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if stringWidth(candidate, font, size) <= max_width:
                    current = candidate
                else:
                    out.append(current)
                    current = word
            out.append(current)
        return out

    def label_row(label: str, value: str) -> None:
        ensure(6 * mm)
        pdf.setFillColor(muted)
        pdf.setFont(regular, 8.5)
        pdf.drawString(left, state["y"], label)
        pdf.setFillColor(ink)
        pdf.setFont(regular, 9.5)
        pdf.drawString(left + 32 * mm, state["y"], value)
        state["y"] -= 5.4 * mm

    header()

    # ===== بطاقة بيانات الزيارة =====
    pdf.setFillColor(HexColor("#EAF6F7"))
    pdf.rect(left, state["y"] - 24 * mm, right - left, 28 * mm, stroke=0, fill=1)
    state["y"] -= 2 * mm
    label_row("Patient / المريض", f"{data.patient.display_name}   ·   MRN {data.patient.hospital_mrn}")
    label_row("Clinician / الطبيب",
              data.doctor.full_name + (f"   ·   {data.doctor.specialty}" if data.doctor.specialty else ""))
    label_row("Clinic / العيادة", data.clinic.name if data.clinic else "—")
    label_row("Date / التاريخ", _fmt(data.summary.generated_at))
    state["y"] -= 4 * mm

    # ===== أقسام المذكرة =====
    for section in data.sections:
        title_ar, title_en = data.section_title(section.section_key)
        ensure(14 * mm)
        pdf.setFillColor(teal_dark)
        pdf.setFont(bold, 10.5)
        pdf.drawString(left, state["y"], title_en.upper())
        pdf.setFillColor(muted)
        pdf.setFont(regular, 9)
        pdf.drawRightString(right, state["y"], arabic(title_ar))
        state["y"] -= 2 * mm
        pdf.setStrokeColor(line)
        pdf.setLineWidth(0.5)
        pdf.line(left, state["y"], right, state["y"])
        state["y"] -= 5 * mm

        pdf.setFillColor(ink)
        pdf.setFont(regular, 9.5)
        for row in wrap(section.content_current.strip(), regular, 9.5, right - left):
            ensure(6 * mm)
            pdf.setFillColor(ink)
            pdf.setFont(regular, 9.5)
            pdf.drawString(left, state["y"], row)
            state["y"] -= 4.9 * mm
        state["y"] -= 3 * mm

    # ===== البنود المرمّزة =====
    if data.codes:
        ensure(16 * mm)
        pdf.setFillColor(teal_dark)
        pdf.setFont(bold, 10.5)
        pdf.drawString(left, state["y"], "CODED ITEMS")
        pdf.setFillColor(muted)
        pdf.setFont(regular, 9)
        pdf.drawRightString(right, state["y"], arabic("البنود المرمّزة"))
        state["y"] -= 2 * mm
        pdf.setStrokeColor(line)
        pdf.line(left, state["y"], right, state["y"])
        state["y"] -= 6 * mm

        for item in data.codes:
            _label_ar, label_en = KIND_LABEL.get(item.kind, (item.kind, item.kind))
            ensure(11 * mm)
            pdf.setFillColor(teal)
            pdf.setFont(bold, 8.5)
            pdf.drawString(left, state["y"], label_en)
            pdf.setFillColor(ink)
            pdf.setFont(regular, 9)
            for index, row in enumerate(wrap(item.suggestion_text.strip(), regular, 9, right - left - 30 * mm)):
                if index:
                    ensure(5 * mm)
                pdf.setFillColor(ink)
                pdf.setFont(regular, 9)
                pdf.drawString(left + 30 * mm, state["y"], row)
                state["y"] -= 4.6 * mm
            detail = _code_of(item)
            if item.linked_dx_code:
                detail += f"   ·   linked Dx {item.linked_dx_code}"
            if item.code_registry_version:
                detail += f"   ·   {item.code_registry_version}"
                if item.code_effective_date:
                    detail += f" (eff. {item.code_effective_date})"
            ensure(5 * mm)
            pdf.setFillColor(muted)
            pdf.setFont(regular, 8)
            pdf.drawString(left + 30 * mm, state["y"], detail)
            state["y"] -= 5.6 * mm
            if item.justification:
                for row in wrap(f"justification: {item.justification.strip()}", regular, 8, right - left - 30 * mm):
                    ensure(5 * mm)
                    pdf.setFillColor(muted)
                    pdf.setFont(regular, 8)
                    pdf.drawString(left + 30 * mm, state["y"], row)
                    state["y"] -= 4.2 * mm
                state["y"] -= 1.5 * mm

    # ===== بصمتا البوابتين =====
    ensure(22 * mm)
    state["y"] -= 2 * mm
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.2)
    pdf.line(left, state["y"], right, state["y"])
    state["y"] -= 6 * mm
    pdf.setFillColor(teal_dark)
    pdf.setFont(bold, 9)
    pdf.drawString(left, state["y"], "HUMAN APPROVAL")
    pdf.setFillColor(muted)
    pdf.setFont(regular, 8.5)
    pdf.drawRightString(right, state["y"], arabic("الاعتماد البشري"))
    state["y"] -= 5.6 * mm
    if data.note_approval is not None:
        label_row("Gate 1 / بوابة ①",
                  f"{_fmt(data.note_approval.approved_at)}   ·   SHA-256 {data.note_approval.summary_hash[:24]}")
    if data.approval is not None:
        approver = db.execute(select(User).where(User.id == data.approval.approved_by)).scalar_one_or_none()
        label_row("Gate 2 / بوابة ②",
                  f"{_fmt(data.approval.approved_at)}   ·   SHA-256 {data.approval.codes_hash[:24]}")
        label_row("Approved by / اعتمدها", approver.full_name if approver else "—")

    footer()
    pdf.save()
    return buffer.getvalue()


def export_filename(visit: Visit, extension: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    return f"medify-note-{str(visit.id)[:8]}-{stamp}.{extension}"


def export_meta(db: Session, visit: Visit) -> dict[str, Any]:
    data = ExportBundle(db, visit)
    return {
        "sections": len(data.sections),
        "coded_items": len(data.codes),
        "gate1_at": data.note_approval.approved_at.isoformat() if data.note_approval else None,
        "gate2_at": data.approval.approved_at.isoformat() if data.approval else None,
    }
