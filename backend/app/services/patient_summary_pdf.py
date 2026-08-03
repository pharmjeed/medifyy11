"""PDF ملخص المريض — عربي RTL كامل بخط IBM Plex Sans Arabic (م14).

بخلاف مذكرة الطبيب (LTR إنجليزية)، هذا المخرج للمريض: كل النص عربي مُشكَّل
باتجاه صحيح ومحاذاة يمين، بلغة بسيطة وبنية خمسة أقسام ثابتة.
"""
from __future__ import annotations

import datetime as dt
import io
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Clinic, Facility, Patient, User, Visit
from .export import _ar, _fmt, _register_fonts, _FONT_BOLD, _FONT_REGULAR

SECTION_TITLES = [
    ("diagnosis", "التشخيص"),
    ("medications", "الأدوية وكيفية الاستخدام"),
    ("instructions", "التعليمات"),
    ("follow_up", "موعد المراجعة"),
    ("red_flags", "علامات الخطر — راجع الطوارئ فوراً"),
]


def _version_footer_line(db: Session, visit: Visit, version_number: int) -> str | None:
    """تذييل النسخة (م6) — إلزامي على كل قالب تصدير بما فيه ملخص المريض (م19 §5)."""
    from ..models import NoteVersion

    row = db.execute(
        select(NoteVersion).where(
            NoteVersion.visit_id == visit.id,
            NoteVersion.version_number == version_number,
        )
    ).scalar_one_or_none()
    if row is None or row.uploaded_at is None:
        return None
    stamp = _fmt(row.uploaded_at)
    return (f"النسخة {row.version_number} — اعتُمدت ونُقلت بتاريخ {stamp} — "
            "يُرجع لملف المريض في نظام المستشفى للنسخة السارية")


def patient_summary_pdf(db: Session, visit: Visit, stored: dict[str, Any]) -> bytes:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas as pdfcanvas

    facility = db.execute(select(Facility).where(Facility.id == visit.facility_id)).scalar_one()
    patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one()
    doctor = db.execute(select(User).where(User.id == visit.doctor_id)).scalar_one()
    clinic = db.execute(select(Clinic).where(Clinic.id == visit.clinic_id)).scalar_one_or_none()
    summary = stored["summary"]

    fonts_ok = _register_fonts()
    regular = _FONT_REGULAR if fonts_ok else "Helvetica"
    bold = _FONT_BOLD if fonts_ok else "Helvetica-Bold"

    def arabic(text: str) -> str:
        return _ar(text) if fonts_ok else text

    teal = HexColor("#0E7C86")
    teal_dark = HexColor("#0A5C64")
    gold = HexColor("#C9A227")
    ink = HexColor("#0F2233")
    muted = HexColor("#5B7280")
    line = HexColor("#D7E3E8")
    danger = HexColor("#A13333")

    buffer = io.BytesIO()
    pdf = pdfcanvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left, right = 18 * mm, width - 18 * mm
    state = {"y": height - 16 * mm, "page": 0}

    def footer() -> None:
        pdf.setStrokeColor(line)
        pdf.setLineWidth(0.6)
        pdf.line(left, 18 * mm, right, 18 * mm)
        pdf.setFillColor(muted)
        pdf.setFont(regular, 7.5)
        pdf.drawRightString(right, 13.5 * mm, arabic(
            "هذا الملخص للتوعية فقط — راجع طبيبك عند أي استفسار. أُنتج عبر Medify."))
        pdf.drawCentredString(width / 2, 9.5 * mm, str(state["page"]))

    def header() -> None:
        state["page"] += 1
        pdf.setFillColor(teal)
        pdf.setFont(bold, 15)
        pdf.drawRightString(right, state["y"], arabic(facility.name))
        pdf.setFillColor(teal_dark)
        pdf.setFont(bold, 12)
        pdf.drawRightString(right, state["y"] - 7 * mm, arabic("ملخص زيارتك"))
        pdf.setStrokeColor(gold)
        pdf.setLineWidth(1.6)
        pdf.line(left, state["y"] - 10 * mm, right, state["y"] - 10 * mm)
        state["y"] -= 17 * mm

    def ensure(space: float) -> None:
        if state["y"] - space < 26 * mm:
            footer()
            pdf.showPage()
            state["y"] = height - 16 * mm
            header()

    def wrap_ar(text: str, font: str, size: float, max_width: float) -> list[str]:
        """لفّ عربي على مستوى الكلمات — التشكيل والاتجاه يُطبَّقان عند الرسم."""
        out: list[str] = []
        for paragraph in (text or "").replace("\r", "").split("\n"):
            words = paragraph.split()
            if not words:
                out.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if stringWidth(arabic(candidate), font, size) <= max_width:
                    current = candidate
                else:
                    out.append(current)
                    current = word
            out.append(current)
        return out

    header()

    # بطاقة بيانات المريض — كلها يمين
    pdf.setFillColor(HexColor("#EAF6F7"))
    pdf.rect(left, state["y"] - 18 * mm, right - left, 22 * mm, stroke=0, fill=1)
    state["y"] -= 2 * mm
    for label, value in (
        ("الاسم", patient.display_name),
        ("الطبيب", doctor.full_name),
        ("العيادة", clinic.name if clinic else "—"),
        ("التاريخ", _fmt(dt.datetime.now(dt.timezone.utc))),
    ):
        pdf.setFillColor(ink)
        pdf.setFont(regular, 9.5)
        pdf.drawRightString(right - 2 * mm, state["y"], arabic(f"{label}: {value}"))
        state["y"] -= 5.2 * mm
    state["y"] -= 5 * mm

    for key, title in SECTION_TITLES:
        content = str(summary.get(key, "") or "").strip()
        if not content:
            continue
        is_danger = key == "red_flags"
        ensure(16 * mm)
        pdf.setFillColor(danger if is_danger else teal_dark)
        pdf.setFont(bold, 11.5)
        pdf.drawRightString(right, state["y"], arabic(title))
        state["y"] -= 2.5 * mm
        pdf.setStrokeColor(danger if is_danger else line)
        pdf.setLineWidth(0.8 if is_danger else 0.5)
        pdf.line(left, state["y"], right, state["y"])
        state["y"] -= 6 * mm

        pdf.setFillColor(danger if is_danger else ink)
        pdf.setFont(regular, 10.5)
        for row in wrap_ar(content, regular, 10.5, right - left - 4 * mm):
            ensure(6 * mm)
            pdf.setFillColor(danger if is_danger else ink)
            pdf.setFont(regular, 10.5)
            pdf.drawRightString(right - 2 * mm, state["y"], arabic(row))
            state["y"] -= 5.6 * mm
        state["y"] -= 4 * mm

    # م19 §5: تذييل النسخة إلزامي على كل قالب — بما فيه ملخص المريض
    version_line = _version_footer_line(db, visit, stored.get("version_number", visit.cycle))
    if version_line is not None:
        ensure(10 * mm)
        pdf.setStrokeColor(line)
        pdf.setLineWidth(0.5)
        pdf.line(left, state["y"], right, state["y"])
        state["y"] -= 5 * mm
        pdf.setFillColor(muted)
        pdf.setFont(regular, 8)
        for row in wrap_ar(version_line, regular, 8, right - left - 4 * mm):
            ensure(5 * mm)
            pdf.drawRightString(right - 2 * mm, state["y"], arabic(row))
            state["y"] -= 4.4 * mm

    footer()
    pdf.save()
    return buffer.getvalue()
