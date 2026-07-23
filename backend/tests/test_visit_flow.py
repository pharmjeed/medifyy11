"""الرحلة الكاملة E2E — دخول → مريض → قالب → تسجيل/تفريغ → ملخص → إرشادات →
تحرير ثلاثي → اعتماد → رفع (وهمي) → السجل واللوحات (معيار القبول الثالث)."""
from __future__ import annotations

import pytest

from tests.conftest import auth, record_consent


@pytest.fixture(scope="module")
def journey(client, doctor_token):
    """تنشئ زيارة كاملة حتى in_review وتعيد معرفاتها."""
    headers = auth(doctor_token)

    patients = client.get("/api/v1/patients", headers=headers, params={"query": "العتيبي"}).json()["data"]
    assert patients and patients[0]["hospital_mrn"] == "1042376"
    patient_id = patients[0]["id"]

    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    personal = [t for t in templates if t["is_personal"]]
    assert personal, "قالب دكتور أحمد الشخصي من seed"
    template_id = personal[0]["id"]
    assert len(personal[0]["structure"]["sections"]) == 5  # يشمل تثقيف المريض E

    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": template_id})
    assert created.status_code == 201, created.text
    visit = created.json()["data"]
    assert visit["state"] == "draft"
    assert visit["context_snapshot"]["problems"], "لقطة الملف التاريخي تُجلب عند الإنشاء (FR-601)"
    visit_id = visit["id"]

    # A1: التسجيل بلا موافقة موثّقة يُرفض بـ MDF-4230
    blocked = client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["error"]["code"] == "MDF-4230"
    record_consent(client, visit_id, headers)

    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/recording/pause", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/recording/resume", headers=headers).status_code == 200

    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 92, "pauses_count": 1, "offline_chunks": 0})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["data"]["state"] == "in_review"
    return {"visit_id": visit_id, "headers": headers}


def test_summary_generated_dynamically_from_template(client, journey):
    response = client.get(f"/api/v1/visits/{journey['visit_id']}/summary", headers=journey["headers"])
    assert response.status_code == 200
    data = response.json()["data"]
    keys = [section["section_key"] for section in data["sections"]]
    assert keys == ["S", "O", "A", "P", "E"], "الأقسام من بنية القالب ديناميكياً — لا SOAP مثبتة"
    assert response.headers.get("ETag")
    assert data["pending_guidance_count"] >= 1
    guidance = [g for section in data["sections"] for g in section["guidance"]]
    assert all(g["evidence_source"] in ("patient_file", "current_visit") for g in guidance)
    assert all(g["evidence_ref"] for g in guidance), "لا اقتراح بلا تعليل (DOC-03 §٦)"


def test_transcript_kept_linked_to_visit(client, journey):
    response = client.get(f"/api/v1/visits/{journey['visit_id']}/transcript", headers=journey["headers"])
    assert response.status_code == 200
    segments = response.json()["data"]["content"]["segments"]
    assert len(segments) >= 5
    assert all("t0" in segment for segment in segments)


def test_typing_edit_requires_etag_and_logs_event(client, journey):
    headers = journey["headers"]
    visit_id = journey["visit_id"]
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    section = summary["sections"][0]

    no_etag = client.patch(f"/api/v1/summary-sections/{section['id']}",
                           headers=headers, json={"content_current": "X"})
    assert no_etag.status_code == 412
    assert no_etag.json()["error"]["code"] == "MDF-4224"

    stale = client.patch(f"/api/v1/summary-sections/{section['id']}",
                         headers={**headers, "If-Match": "stale-etag"},
                         json={"content_current": "X"})
    assert stale.status_code == 412  # W-222

    good = client.patch(f"/api/v1/summary-sections/{section['id']}",
                        headers={**headers, "If-Match": summary["etag"]},
                        json={"content_current": section["content_current"] + " Edited by typing."})
    assert good.status_code == 200, good.text
    assert good.json()["data"]["etag"] != summary["etag"]


def test_voice_dictation_merges_into_section(client, journey):
    headers = journey["headers"]
    summary = client.get(f"/api/v1/visits/{journey['visit_id']}/summary", headers=headers).json()["data"]
    section = summary["sections"][1]
    response = client.post(f"/api/v1/summary-sections/{section['id']}/dictate",
                           headers={**headers, "If-Match": summary["etag"]},
                           json={"mode": "append"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["dictated_text"] in data["content_current"]


def test_ai_chat_applies_patches_with_diff(client, journey):
    headers = journey["headers"]
    response = client.post(f"/api/v1/visits/{journey['visit_id']}/ai-chat", headers=headers,
                           json={"message": "أضف إلى الخطة قياس الضغط المنزلي مرتين يومياً مع تسجيل القراءات."})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply"]
    assert data["patches"], "الفروقات تُطبق وتُعرض (FR-707)"
    assert {"old_content", "new_content", "section_key"} <= set(data["patches"][0].keys())


def test_ai_chat_ambiguous_returns_question_no_patch(client, journey):
    response = client.post(f"/api/v1/visits/{journey['visit_id']}/ai-chat",
                           headers=journey["headers"], json={"message": "عدّل"})
    data = response.json()["data"]
    assert data["patches"] == []
    assert "؟" in data["reply"]


def test_low_confidence_code_is_withheld_until_doctor_input(client, journey):
    """A5 «لا تخمين»: كود دون العتبة يُحجب ويُعلَّم requires_doctor_input — خانة فارغة."""
    summary = client.get(f"/api/v1/visits/{journey['visit_id']}/summary",
                         headers=journey["headers"]).json()["data"]
    guidance = [g for section in summary["sections"] for g in section["guidance"]]
    withheld = [g for g in guidance if g["requires_doctor_input"]]
    assert withheld, "عيّنة P3 تتضمن بنداً دون العتبة"
    for item in withheld:
        assert item["code_value"] is None, "الكود المحجوب لا يخرج إطلاقاً"
        assert item["code_system"] is None
    assert summary["awaiting_doctor_input_count"] == 0  # لا شيء محسوم بعد


def test_structured_plan_items_keep_mandated_code_systems(client, journey):
    """توجيه المالك: دواء SFDA · جهاز GMDN — لا تُقسر أنظمة الخطة على النظام التشخيصي."""
    summary = client.get(f"/api/v1/visits/{journey['visit_id']}/summary",
                         headers=journey["headers"]).json()["data"]
    guidance = [g for section in summary["sections"] for g in section["guidance"]]
    by_kind = {g["kind"]: g for g in guidance}
    if "clinical_device" in by_kind:
        device = by_kind["clinical_device"]
        assert device["code_system"] == "GMDN", "الجهاز يحمل GMDN لا ICD10AM"
        assert device["code_secondary_system"] == "GTIN"
        assert device["justification"], "الجهاز يحمل مبرراً إلزامياً"
        assert device["linked_dx_code"], "كل بند خطة مرتبط بتشخيص"
    if "clinical_rx" in by_kind:
        assert by_kind["clinical_rx"]["code_system"] == "SFDA"


def test_note_approve_gate_precedes_code_approve(client, journey):
    """A2: البوابة ② مرفوضة قبل ① (MDF-4231)، ثم ① تجمّد نص المذكرة."""
    headers = journey["headers"]
    visit_id = journey["visit_id"]

    # ② قبل ① مرفوضة
    early = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert early.status_code == 422
    assert early.json()["error"]["code"] in ("MDF-4231", "MDF-4222")

    note = client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers)
    assert note.status_code == 200, note.text
    assert note.json()["data"]["note_approved"] is True
    assert note.json()["data"]["summary_hash"]

    # بعد ① يتجمّد نص المذكرة (MDF-4226) لكن حسم الأكواد يبقى مفتوحاً
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    assert summary["note_approved"] is True
    assert summary["can_export"] is False
    section = summary["sections"][0]
    frozen = client.patch(f"/api/v1/summary-sections/{section['id']}",
                          headers={**headers, "If-Match": summary["etag"]},
                          json={"content_current": "post-gate1 edit"})
    assert frozen.status_code == 422
    assert frozen.json()["error"]["code"] == "MDF-4226"


def test_approve_blocked_with_pending_guidance_mdf4222(client, journey):
    response = client.post(f"/api/v1/visits/{journey['visit_id']}/approve", headers=journey["headers"])
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "MDF-4222"
    assert error["details"]["pending_count"] >= 1


def test_resolve_guidance_then_approve_and_upload(client, journey):
    headers = journey["headers"]
    visit_id = journey["visit_id"]
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    pending = [g for section in summary["sections"] for g in section["guidance"] if g["status"] == "pending"]
    assert pending

    # حسم كل بند: المحجوب دون العتبة يتطلب إدخال كود (وإلا حجب الاعتماد)، وغيره يُقبل/يُعدَّل
    for index, item in enumerate(pending):
        if item["requires_doctor_input"]:
            # A5: الطبيب يُدخل الكود بوعي فيسقط الحجب
            resolved = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers, json={
                "status": "modified",
                "modified_text": item["suggestion_text"] + " — clinician-entered code",
                "modified_code_system": "ICD10AM",
                "modified_code_value": "G44.2",
            })
            assert resolved.status_code == 200
            assert resolved.json()["data"]["requires_doctor_input"] is False
        elif index == 0:
            resolved = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                                    json={"status": "accepted"})
            assert resolved.status_code == 200
        else:
            client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers, json={"status": "rejected"})

    # البوابة ① أولاً (إن لم تكن أُنجزت في اختبار سابق)
    client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers)

    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    data = approved.json()["data"]
    assert data["approved"] is True
    assert data["upload"]["status"] == "confirmed"  # وجهة وهمية تنجح (INTEGRATION_ENGINE=mock)

    status = client.get(f"/api/v1/visits/{visit_id}/upload-status", headers=headers).json()["data"]
    assert status["state"] == "uploaded"
    assert status["attempts"][0]["result"] == "confirmed"

    listed = client.get("/api/v1/visits", headers=headers, params={"per_page": 100}).json()["data"]
    row = next(v for v in listed if v["id"] == visit_id)
    assert row["state"] == "uploaded"
    assert row["upload_status"] == "confirmed"


def test_edit_after_approval_rejected_mdf4226(client, journey):
    headers = journey["headers"]
    summary = client.get(f"/api/v1/visits/{journey['visit_id']}/summary", headers=headers).json()["data"]
    section = summary["sections"][0]
    response = client.patch(f"/api/v1/summary-sections/{section['id']}",
                            headers={**headers, "If-Match": summary["etag"]},
                            json={"content_current": "tamper attempt"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MDF-4226"


def test_double_approve_rejected(client, journey):
    response = client.post(f"/api/v1/visits/{journey['visit_id']}/approve", headers=journey["headers"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MDF-4223"


def test_cancel_after_recording_rejected_mdf4227(client, journey):
    response = client.post(f"/api/v1/visits/{journey['visit_id']}/cancel", headers=journey["headers"])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MDF-4227"


def test_cancel_from_draft_is_final(client, doctor_token):
    headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=headers, params={"query": "1029841"}).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers, json={
        "patient_id": patients[0]["id"], "template_id": templates[0]["id"],
    }).json()["data"]
    cancelled = client.post(f"/api/v1/visits/{created['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["state"] == "cancelled"
    # نهائية: لا تسجيل بعد الإلغاء
    start = client.post(f"/api/v1/visits/{created['id']}/recording/start", headers=headers)
    assert start.status_code == 409
    assert start.json()["error"]["code"] == "MDF-4223"


def test_visit_appears_in_admin_dashboards_as_counters_only(client, admin_token):
    usage = client.get("/api/v1/dashboards/usage", headers=auth(admin_token)).json()["data"]
    assert usage["total_visits"] >= 12
    assert usage["by_state"].get("uploaded", 0) >= 6
    quality = client.get("/api/v1/dashboards/quality", headers=auth(admin_token)).json()["data"]
    assert "guidance_by_status" in quality
    flattened = str(usage) + str(quality)
    assert "hypertension" not in flattened.lower(), "لا محتوى سريرياً في لوحات الأدمن"
