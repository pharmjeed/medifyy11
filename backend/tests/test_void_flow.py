"""مسار الإبطال Void من in_review (قرار مالك 2026-08-03) — Void ≠ Delete.

زيارة اكتملت معالجتها ولا يصح اعتمادها (مريض خطأ / مكررة / تجريبية / سحب موافقة):
تُبطل بسبب مدوَّن في سجل التدقيق، تُختم للقراءة، وتخرج من الإحصائيات وملف المريض —
بينما واقعة الإبطال نفسها تبقى (لا حذف).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import auth, record_consent


def _void_test_patient(client, headers) -> str:
    """مريض مخصص لاختبارات الإبطال — لا يلوّث لقطات سياق مرضى seed التي ترتكز عليها رحلات أخرى."""
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900777", "display_name": "مريض اختبار الإبطال"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def _visit_to_in_review(client, headers, patient_id: str) -> str:
    """زيارة كاملة حتى in_review — نفس رحلة test_visit_flow مختصرة."""
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers, json={
        "patient_id": patient_id, "template_id": templates[0]["id"],
    })
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 40})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["data"]["state"] == "in_review"
    return visit_id


@pytest.fixture(scope="module")
def void_patient(client, doctor_token) -> str:
    return _void_test_patient(client, auth(doctor_token))


@pytest.fixture(scope="module")
def voided_visit(client, doctor_token, void_patient) -> dict:
    """زيارة in_review تُبطل بنجاح — أساس بقية الاختبارات."""
    headers = auth(doctor_token)
    visit_id = _visit_to_in_review(client, headers, void_patient)
    response = client.post(f"/api/v1/visits/{visit_id}/void", headers=headers,
                           json={"reason": "wrong_patient", "note": "مريضان بنفس الاسم"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["state"] == "voided"
    return {"visit_id": visit_id, "headers": headers}


def test_void_recorded_in_audit_log_with_actor_and_reason(client, voided_visit, admin_token):
    """واقعة الإبطال تبقى: من أبطل، ولماذا، ومتى — في السجل الإلحاقي."""
    logs = client.get("/api/v1/audit-logs", headers=auth(admin_token),
                      params={"action": "visit.voided", "per_page": 100}).json()["data"]
    entry = next((row for row in logs if row["entity_id"] == voided_visit["visit_id"]), None)
    assert entry is not None, "visit.voided يجب أن يُدوَّن في audit_logs"
    assert entry["meta"]["reason"] == "wrong_patient"
    assert entry["meta"]["note"] == "مريضان بنفس الاسم"
    assert entry["actor"] != "النظام", "الفاعل هوية بشرية لا النظام"
    assert entry["at"]


def test_void_requires_reason_from_catalog(client, doctor_token, void_patient):
    """سبب خارج القائمة أو «أخرى» بلا توضيح = 422 بمغلف التحقق القياسي (م4 — كان 404 خطأً)."""
    headers = auth(doctor_token)
    visit_id = _visit_to_in_review(client, headers, void_patient)
    bad = client.post(f"/api/v1/visits/{visit_id}/void", headers=headers,
                      json={"reason": "changed_my_mind"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "MDF-5001"

    # «أخرى» بلا توضيح نصي مرفوضة
    other = client.post(f"/api/v1/visits/{visit_id}/void", headers=headers,
                        json={"reason": "other", "note": "  "})
    assert other.status_code == 422
    assert other.json()["error"]["code"] == "MDF-5001"

    # «أخرى» بتوضيح تمر
    good = client.post(f"/api/v1/visits/{visit_id}/void", headers=headers,
                       json={"reason": "other", "note": "تسجيل أثناء عرض تدريبي"})
    assert good.status_code == 200, good.text


def test_void_blocked_outside_in_review(client, doctor_token, void_patient):
    """قبل المعالجة المسار هو الإلغاء (FR-606) — الإبطال من in_review حصراً."""
    headers = auth(doctor_token)
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    draft = client.post("/api/v1/visits", headers=headers, json={
        "patient_id": void_patient, "template_id": templates[0]["id"],
    }).json()["data"]
    blocked = client.post(f"/api/v1/visits/{draft['id']}/void", headers=headers,
                          json={"reason": "test"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "MDF-4223"
    # تنظيف: المسودة تُلغى بمسارها الشرعي
    assert client.post(f"/api/v1/visits/{draft['id']}/cancel", headers=headers).status_code == 200


def test_voided_is_terminal_and_sealed(client, voided_visit):
    """نهائية voided: لا اعتماد ولا بوابة ① ولا تحرير ولا إبطال ثانٍ."""
    headers = voided_visit["headers"]
    visit_id = voided_visit["visit_id"]

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    assert summary["state"] == "voided"

    note_gate = client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers)
    assert note_gate.status_code == 409
    assert note_gate.json()["error"]["code"] == "MDF-4223"

    approve = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approve.status_code == 409
    assert approve.json()["error"]["code"] == "MDF-4223"

    section = summary["sections"][0]
    edit = client.patch(f"/api/v1/summary-sections/{section['id']}",
                        headers={**headers, "If-Match": summary["etag"]},
                        json={"content_current": "post-void tamper"})
    assert edit.status_code == 422
    assert edit.json()["error"]["code"] == "MDF-4226"

    again = client.post(f"/api/v1/visits/{visit_id}/void", headers=headers,
                        json={"reason": "duplicate"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "MDF-4223"


def test_voided_terminal_at_db_level_and_audio_follows_retention(owner_engine, voided_visit):
    """الحكم النهائي للقاعدة: voided → approved مرفوض بالـ trigger.
    والصوت لا يُحذف عند الإبطال — يتبع سياسة الاحتفاظ ذاتها (retention_until)."""
    visit_id = voided_visit["visit_id"]
    with owner_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="MDF-4223"):
            with conn.begin_nested():
                conn.execute(text("UPDATE visits SET state = 'approved' WHERE id = :id"), {"id": visit_id})
        recording = conn.execute(text(
            "SELECT retention_until, deleted_at FROM recordings WHERE visit_id = :id"
        ), {"id": visit_id}).fetchone()
        assert recording is not None
        assert recording.deleted_at is None, "الإبطال لا يحذف الصوت فوراً — الحذف بسياسة الاحتفاظ"
        assert recording.retention_until is not None


def test_voided_excluded_from_dashboards_but_visible_in_state_distribution(client, doctor_token, admin_token, void_patient):
    """المبطلة خارج عدادات الإنتاجية والجودة — وتبقى ظاهرة في توزيع الحالات (شفافية)."""
    doctor_headers = auth(doctor_token)
    admin_headers = auth(admin_token)

    visit_id = _visit_to_in_review(client, doctor_headers, void_patient)
    usage_before = client.get("/api/v1/dashboards/usage", headers=admin_headers).json()["data"]
    quality_before = client.get("/api/v1/dashboards/quality", headers=admin_headers).json()["data"]

    voided = client.post(f"/api/v1/visits/{visit_id}/void", headers=doctor_headers,
                         json={"reason": "duplicate"})
    assert voided.status_code == 200, voided.text

    usage_after = client.get("/api/v1/dashboards/usage", headers=admin_headers).json()["data"]
    quality_after = client.get("/api/v1/dashboards/quality", headers=admin_headers).json()["data"]

    assert usage_after["total_visits"] == usage_before["total_visits"] - 1
    assert usage_after["by_state"].get("voided", 0) == usage_before["by_state"].get("voided", 0) + 1
    assert sum(d["visits"] for d in usage_after["by_doctor"]) == sum(d["visits"] for d in usage_before["by_doctor"]) - 1
    # لوحة الجودة: صفوف المحتوى السريري محجوبة عن الأدمن أصلاً (RLS) فلا دلتا تُقاس —
    # يكفي أن الإبطال لا يغيّر مؤشراتها (المبطلة خارجها بالبناء)
    assert quality_after == quality_before


def test_void_from_summarized_and_approved_pre_upload(client, doctor_token, void_patient, owner_engine):
    """مصادر الإبطال الموسّعة (م4): summarized وapproved قبل النقل عبر API نفسها."""
    headers = auth(doctor_token)
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]

    def _consented_draft() -> str:
        created = client.post("/api/v1/visits", headers=headers,
                              json={"patient_id": void_patient, "template_id": templates[0]["id"]})
        assert created.status_code == 201, created.text
        visit_id = created.json()["data"]["id"]
        record_consent(client, visit_id, headers)
        return visit_id

    # summarized (مشي مملوك للقاعدة — stop عبر API يمضي إلى in_review دفعة واحدة)
    v1 = _consented_draft()
    with owner_engine.begin() as conn:
        for state in ("recording", "transcribed", "summarized"):
            conn.execute(text("UPDATE visits SET state = :s WHERE id = :id"), {"s": state, "id": v1})
    voided = client.post(f"/api/v1/visits/{v1}/void", headers=headers, json={"reason": "test_recording"})
    assert voided.status_code == 200, voided.text
    assert voided.json()["data"]["state"] == "voided"

    # approved قبل النقل
    v2 = _consented_draft()
    with owner_engine.begin() as conn:
        for state in ("recording", "transcribed", "summarized", "in_review", "approved"):
            conn.execute(text("UPDATE visits SET state = :s WHERE id = :id"), {"s": state, "id": v2})
    voided2 = client.post(f"/api/v1/visits/{v2}/void", headers=headers, json={"reason": "duplicate"})
    assert voided2.status_code == 200, voided2.text


def test_admin_can_void_doctor_visit(client, doctor_token, admin_token, void_patient):
    """RBAC (م4): أدمن المنشأة يبطل زيارة الدكتور — فعل إداري على الحالة بلا قراءة محتوى."""
    doctor_headers = auth(doctor_token)
    visit_id = _visit_to_in_review(client, doctor_headers, void_patient)
    voided = client.post(f"/api/v1/visits/{visit_id}/void", headers=auth(admin_token),
                         json={"reason": "consent_withdrawn"})
    assert voided.status_code == 200, voided.text

    logs = client.get("/api/v1/audit-logs", headers=auth(admin_token),
                      params={"action": "visit.voided", "per_page": 100}).json()["data"]
    entry = next(row for row in logs if row["entity_id"] == visit_id)
    assert entry["meta"]["actor_role"] == "admin"


def test_voided_exports_return_410(client, doctor_token, void_patient):
    """Void ≠ Delete لكنه ختم: أي مخرج لزيارة مُبطلة = 410 MDF-4235 (م4)."""
    headers = auth(doctor_token)
    visit_id = _visit_to_in_review(client, headers, void_patient)
    assert client.post(f"/api/v1/visits/{visit_id}/void", headers=headers,
                       json={"reason": "wrong_patient"}).status_code == 200

    text_export = client.get(f"/api/v1/visits/{visit_id}/export/text", headers=headers)
    assert text_export.status_code == 410
    assert text_export.json()["error"]["code"] == "MDF-4235"

    pdf_export = client.get(f"/api/v1/visits/{visit_id}/export/pdf", headers=headers)
    assert pdf_export.status_code == 410
    assert pdf_export.json()["error"]["code"] == "MDF-4235"


def test_voided_excluded_from_patient_history(client, doctor_token, void_patient):
    """زيارة مبطلة (مريض خطأ) لا تدخل ملف المريض ولا سياق الإرشاد لاحقاً."""
    headers = auth(doctor_token)
    voided_id = _visit_to_in_review(client, headers, void_patient)
    assert client.post(f"/api/v1/visits/{voided_id}/void", headers=headers,
                       json={"reason": "wrong_patient"}).status_code == 200

    next_id = _visit_to_in_review(client, headers, void_patient)
    summary = client.get(f"/api/v1/visits/{next_id}/summary", headers=headers).json()["data"]
    history_ids = {row["visit_id"] for row in summary["previous_visits"]}
    assert voided_id not in history_ids, "المبطلة ليست مراجعة سابقة"

    # وتبقى ظاهرة في سجل زيارات الدكتور نفسه (Void ≠ Delete)
    listed = client.get("/api/v1/visits", headers=headers,
                        params={"state": "voided", "per_page": 100}).json()["data"]
    assert voided_id in {row["id"] for row in listed}
