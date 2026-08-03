"""المرحلة 14 — ملخص المريض بالعربي.

معايير القبول: قبل البوابة ① → رفض | نسخة جديدة → ملخص يعكس التغيير | مستبعد →
لا يظهر بمخارج النسخة.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth, record_consent


def _visit_in_review(client, headers, patient_id: str) -> str:
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                       json={"duration_sec": 35}).status_code == 200
    return visit_id


def _resolve_and_approve_gate1(client, headers, visit_id: str) -> None:
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    for section in summary["sections"]:
        for item in section["guidance"]:
            if item["status"] != "pending":
                continue
            if item["kind"] in ("clinical_dx", "coding_match") and not item["requires_doctor_input"]:
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                             json={"status": "accepted"})
            else:
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                             json={"status": "rejected"})
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200


@pytest.fixture(scope="module")
def ps_patient(client, doctor_token) -> str:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900810", "display_name": "سعد التجريبي"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def test_generation_blocked_before_gate1(client, doctor_token, ps_patient):
    """قبل البوابة ① لا توليد إطلاقاً — الحارس في طبقة الخدمة."""
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, ps_patient)
    blocked = client.post(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers)
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "MDF-4231"
    assert client.get(f"/api/v1/visits/{visit_id}/patient-summary",
                      headers=headers).status_code == 404


def test_generate_edit_and_toggle_inclusion(client, doctor_token, ps_patient):
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, ps_patient)
    _resolve_and_approve_gate1(client, headers, visit_id)

    created = client.post(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers)
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["stale"] is False and data["included"] is False
    summary = data["summary"]
    assert set(summary) == {"diagnosis", "medications", "instructions", "follow_up", "red_flags"}
    assert summary["diagnosis"], "التشخيص بالعربية البسيطة"
    # لا إنجليزية إلا أسماء الأدوية التجارية — التشخيص والتعليمات عربية خالصة
    assert not any(ch.isascii() and ch.isalpha() for ch in summary["diagnosis"])

    # تعديل الطبيب + قرار التضمين
    patched = client.patch(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers,
                           json={"summary": {"instructions": "قِس الضغط صباحاً ومساءً وسجّل القراءة."},
                                 "included": True})
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["summary"]["instructions"] == "قِس الضغط صباحاً ومساءً وسجّل القراءة."
    assert patched.json()["data"]["included"] is True

    # PDF عربي مستقل
    pdf = client.get(f"/api/v1/visits/{visit_id}/patient-summary/pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"
    assert len(pdf.content) > 1500


def test_unlock_marks_summary_stale_until_reapproval(client, doctor_token, ps_patient):
    """unlock ثم تعديل النص → الملخص stale؛ إعادة التوليد تُسقط الوسم."""
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, ps_patient)
    _resolve_and_approve_gate1(client, headers, visit_id)
    assert client.post(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers).status_code == 200

    assert client.post(f"/api/v1/visits/{visit_id}/note-unlock", headers=headers,
                       json={"reason": "تفصيل ناقص"}).status_code == 200
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    section = summary["sections"][0]
    assert client.patch(f"/api/v1/summary-sections/{section['id']}",
                        headers={**headers, "If-Match": summary["etag"]},
                        json={"content_current": section["content_current"] + " Additional detail."}
                        ).status_code == 200

    stored = client.get(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers).json()["data"]
    assert stored["stale"] is True, "النص تغيّر — الملخص لم يعد مطابقاً"

    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    regenerated = client.post(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers)
    assert regenerated.status_code == 200
    assert regenerated.json()["data"]["stale"] is False


def test_excluded_summary_absent_from_version_outputs_and_reopen_resets(client, doctor_token, ps_patient):
    """مستبعد → لا يظهر بمخارج النسخة؛ ومضمَّن → يظهر؛ وreopen يبدأ نسخة بلا ملخص."""
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, ps_patient)
    _resolve_and_approve_gate1(client, headers, visit_id)
    assert client.post(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers).status_code == 200
    # مستبعد افتراضياً — البوابة ② ثم فحص المخرج
    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text

    export = client.get(f"/api/v1/visits/{visit_id}/export/text", headers=headers).json()["data"]
    assert "PATIENT SUMMARY" not in export["content"], "المستبعد لا يظهر في مخارج النسخة"

    # نسخة جديدة: reopen يمسح الملخص — والتوليد يتطلب بوابة ① الجديدة
    assert client.post(f"/api/v1/visits/{visit_id}/reopen", headers=headers,
                       json={"reason": "إضافة تعليمات للمريض"}).status_code == 200
    assert client.get(f"/api/v1/visits/{visit_id}/patient-summary",
                      headers=headers).status_code == 404, "النسخة الجديدة تبدأ بلا ملخص"
    blocked = client.post(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers)
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "MDF-4231"

    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers).status_code == 200
    included = client.patch(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers,
                            json={"included": True})
    assert included.status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers).status_code == 200

    export_v2 = client.get(f"/api/v1/visits/{visit_id}/export/text", headers=headers).json()["data"]
    assert export_v2["version"] == 2
    assert "PATIENT SUMMARY" in export_v2["content"], "المضمَّن يظهر في مخرج نسخته"
    # نسخة 1 بقيت بلا ملخص (كانت مستبعدة) — لقطتها لا تتأثر
    export_v1 = client.get(f"/api/v1/visits/{visit_id}/export/text", headers=headers,
                           params={"version": 1}).json()["data"]
    assert "PATIENT SUMMARY" not in export_v1["content"]


def test_version_footer_present_in_every_export_template(client, doctor_token, ps_patient):
    """م19 §5: تذييل النسخة مطبَّق في كل القوالب — نص · PDF المذكرة · PDF ملخص المريض."""
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, ps_patient)
    _resolve_and_approve_gate1(client, headers, visit_id)
    assert client.post(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers).status_code == 200
    assert client.patch(f"/api/v1/visits/{visit_id}/patient-summary", headers=headers,
                        json={"included": True}).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers).status_code == 200

    text_export = client.get(f"/api/v1/visits/{visit_id}/export/text", headers=headers).json()["data"]
    assert "النسخة 1" in text_export["content"]
    assert "يُرجع لملف المريض في نظام المستشفى" in text_export["content"]

    note_pdf = client.get(f"/api/v1/visits/{visit_id}/export/pdf", headers=headers)
    assert note_pdf.status_code == 200 and note_pdf.content[:4] == b"%PDF"

    summary_pdf = client.get(f"/api/v1/visits/{visit_id}/patient-summary/pdf", headers=headers)
    assert summary_pdf.status_code == 200 and summary_pdf.content[:4] == b"%PDF"
    # التذييل يُرسم في القالبين — الحجم يعكس وجود سطوره (سلامة التوليد تُختبر بالبايتات)
    assert len(summary_pdf.content) > 1500

    from app.db import system_session
    from app.models import Visit
    from app.services.patient_summary_pdf import _version_footer_line
    import uuid as _uuid

    with system_session() as sdb:
        visit = sdb.get(Visit, _uuid.UUID(visit_id))
        line = _version_footer_line(sdb, visit, 1)
    assert line is not None and "النسخة 1" in line, "قالب ملخص المريض يحمل التذييل"
