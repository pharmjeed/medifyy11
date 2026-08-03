"""مسار Unlock للبوابة ① (قرار مالك 2026-08-03) — حلقة CDI:
مراجعة الأكواد تكشف نقص توثيق → فتح المذكرة بسبب مسجّل → تعديل → إعادة اعتماد ① → البوابة ②.
الحارس: النقض قبل إتمام ② فقط — بعد الاعتماد النهائي المسار Addendum (ترفضه القاعدة نفسها)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import auth, record_consent


@pytest.fixture(scope="module")
def journey(client, doctor_token):
    """زيارة كاملة حتى in_review — مستقلة عن رحلة test_visit_flow."""
    headers = auth(doctor_token)

    patients = client.get("/api/v1/patients", headers=headers, params={"query": "العتيبي"}).json()["data"]
    assert patients, "مريض seed"
    patient_id = patients[0]["id"]

    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    template_id = templates[0]["id"]

    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": template_id})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]

    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 61, "pauses_count": 0, "offline_chunks": 0})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["data"]["state"] == "in_review"
    return {"visit_id": visit_id, "headers": headers}


def _summary(client, journey):
    response = client.get(f"/api/v1/visits/{journey['visit_id']}/summary", headers=journey["headers"])
    assert response.status_code == 200
    return response.json()["data"]


def test_unlock_before_gate1_rejected(client, journey):
    """لا اعتماد ① بعد → لا شيء يُنقض (MDF-4231)."""
    response = client.post(f"/api/v1/visits/{journey['visit_id']}/note-unlock",
                           headers=journey["headers"], json={"reason": "لا شيء لفتحه"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MDF-4231"


def test_unlock_reopens_editing_and_preserves_code_decisions(client, journey):
    """قلب الحلقة: اعتماد ① → تجميد → نقض بسبب → التحرير يعود، قرارات الأكواد كما هي، و② محجوبة."""
    headers = journey["headers"]
    visit_id = journey["visit_id"]

    note = client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers)
    assert note.status_code == 200, note.text
    first_approval_id = note.json()["data"]["note_approval_id"]
    first_hash = note.json()["data"]["summary_hash"]

    # النص مجمّد بعد ① (trigger القاعدة + الحارس التطبيقي)
    summary = _summary(client, journey)
    assert summary["note_approved"] is True
    section = summary["sections"][0]
    frozen = client.patch(f"/api/v1/summary-sections/{section['id']}",
                          headers={**headers, "If-Match": summary["etag"]},
                          json={"content_current": "post-gate1 edit"})
    assert frozen.status_code == 422
    assert frozen.json()["error"]["code"] == "MDF-4226"

    # حسم إرشاد قبل النقض — القرار يجب أن يبقى بعده (الطبيب لا يعيد كل شيء)
    pending = [g for s in summary["sections"] for g in s["guidance"]
               if g["status"] == "pending" and not g["requires_doctor_input"]]
    assert pending, "عيّنة P3 فيها إرشاد قابل للحسم"
    resolved = client.patch(f"/api/v1/guidance-items/{pending[0]['id']}", headers=headers,
                            json={"status": "accepted"})
    assert resolved.status_code == 200
    kept_item_id = pending[0]["id"]

    # سبب فارغ (مسافات) مرفوض — السبب إلزامي للتدقيق
    blank = client.post(f"/api/v1/visits/{visit_id}/note-unlock", headers=headers,
                        json={"reason": "   "})
    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "MDF-4225"

    # النقض بسبب مسجّل — سيناريو CDI: الكود يتطلب تفصيلاً لا يذكره النص
    reason = "كود الكسر يتطلب تحديد الجهة (يمين/يسار) والنص لا يذكرها"
    unlocked = client.post(f"/api/v1/visits/{visit_id}/note-unlock", headers=headers,
                           json={"reason": reason})
    assert unlocked.status_code == 200, unlocked.text
    data = unlocked.json()["data"]
    assert data["note_unlocked"] is True
    assert data["note_approval_id"] == first_approval_id
    assert data["state"] == "in_review"  # الحالة لا تتغير — النقض يطال البوابة لا آلة الحالات

    # النقض مرة ثانية على اعتماد منقوض — لا شيء نشط (MDF-4231)
    again = client.post(f"/api/v1/visits/{visit_id}/note-unlock", headers=headers,
                        json={"reason": "تكرار"})
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "MDF-4231"

    # الملخص يعكس الفتح: البوابة ① غير منجزة والسبب معروض للدكتور
    summary = _summary(client, journey)
    assert summary["note_approved"] is False
    assert summary["gates"]["note"] is None
    assert summary["note_unlock"] is not None
    assert summary["note_unlock"]["reason"] == reason

    # التحرير عاد متاحاً — الدكتور يضيف الجملة الناقصة
    edited = client.patch(f"/api/v1/summary-sections/{section['id']}",
                          headers={**headers, "If-Match": summary["etag"]},
                          json={"content_current": section["content_current"] + " كسر عظم الكعبرة الأيمن."})
    assert edited.status_code == 200, edited.text

    # قرار الكود المحسوم قبل النقض محفوظ
    summary = _summary(client, journey)
    kept = next(g for s in summary["sections"] for g in s["guidance"] if g["id"] == kept_item_id)
    assert kept["status"] == "accepted"

    # البوابة ② محجوبة — الاعتماد المنقوض لا يمررها (فحص ① يسبق فحص الإرشادات)
    gate2 = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert gate2.status_code == 422
    assert gate2.json()["error"]["code"] == "MDF-4231"

    journey["first_approval_id"] = first_approval_id
    journey["first_hash"] = first_hash


def test_reapprove_creates_new_gate1_then_gate2_passes(client, journey):
    """إعادة الاعتماد صف جديد ببصمة النص المعدَّل — ثم البوابة ② تمضي طبيعياً."""
    headers = journey["headers"]
    visit_id = journey["visit_id"]

    reapproved = client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers)
    assert reapproved.status_code == 200, reapproved.text
    data = reapproved.json()["data"]
    assert data["already_approved"] is False, "إعادة الاعتماد إنشاء جديد لا إعادة عرض القديم"
    assert data["note_approval_id"] != journey["first_approval_id"]
    assert data["summary_hash"] != journey["first_hash"], "بصمة جديدة للنص المعدَّل"

    # التجميد عاد يسري
    summary = _summary(client, journey)
    assert summary["note_approved"] is True
    section = summary["sections"][0]
    frozen = client.patch(f"/api/v1/summary-sections/{section['id']}",
                          headers={**headers, "If-Match": summary["etag"]},
                          json={"content_current": "tamper"})
    assert frozen.status_code == 422

    # حسم بقية الإرشادات ثم البوابة ② — قرارات ما قبل النقض لم تُمس
    pending = [g for s in summary["sections"] for g in s["guidance"] if g["status"] == "pending"]
    for item in pending:
        if item["requires_doctor_input"]:
            response = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers, json={
                "status": "modified",
                "modified_text": item["suggestion_text"] + " — كود مُدخل من الطبيب",
                "modified_code_system": "ICD10AM",
                "modified_code_value": "G44.2",
            })
        else:
            response = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                                    json={"status": "rejected"})
        assert response.status_code == 200, response.text

    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["approved"] is True


def test_unlock_after_gate2_rejected_use_addendum(client, journey):
    """بعد الاعتماد النهائي لا Unlock أبداً — المسار Addendum (MDF-4236 المخصص — م5)."""
    response = client.post(f"/api/v1/visits/{journey['visit_id']}/note-unlock",
                           headers=journey["headers"],
                           json={"reason": "محاولة بعد الاعتماد النهائي"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MDF-4236"


def test_hash_compare_one_click_reapprove(client, doctor_token):
    """م5: نقض بلا تعديل → text_unchanged=true وإعادة الاعتماد بنفس البصمة؛
    وبعد تعديل فعلي → text_unchanged=false وبصمة جديدة."""
    headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=headers, params={"query": "العتيبي"}).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patients[0]["id"], "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                       json={"duration_sec": 30}).status_code == 200

    first = client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers)
    assert first.status_code == 200, first.text
    first_hash = first.json()["data"]["summary_hash"]

    # نقض بلا أي تعديل — CDI اكتشف أن التعديل غير لازم مثلاً
    assert client.post(f"/api/v1/visits/{visit_id}/note-unlock", headers=headers,
                       json={"reason": "مراجعة إضافية"}).status_code == 200
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    assert summary["note_unlock"]["text_unchanged"] is True, "النص لم يتغيّر → إعادة اعتماد بنقرة"

    reapproved = client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers)
    assert reapproved.status_code == 200
    assert reapproved.json()["data"]["summary_hash"] == first_hash, "بصمة النص نفسها"

    # نقض ثانٍ ثم تعديل فعلي → الواجهة تعرف أن النص تغيّر
    assert client.post(f"/api/v1/visits/{visit_id}/note-unlock", headers=headers,
                       json={"reason": "الكود يتطلب جهة الإصابة"}).status_code == 200
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    section = summary["sections"][0]
    edited = client.patch(f"/api/v1/summary-sections/{section['id']}",
                          headers={**headers, "If-Match": summary["etag"]},
                          json={"content_current": section["content_current"] + " الجهة اليمنى."})
    assert edited.status_code == 200, edited.text
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    assert summary["note_unlock"]["text_unchanged"] is False
    changed = client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers)
    assert changed.status_code == 200
    assert changed.json()["data"]["summary_hash"] != first_hash


def test_unlock_trail_in_db_and_append_only(owner_engine, journey):
    """الأثر الكامل: صف note_unlocks + حدثا التدقيق (نقض ثم إعادة اعتماد) — وكله إلحاقي حتى للمالك."""
    visit_id = journey["visit_id"]
    with owner_engine.connect() as conn:
        unlocks = conn.execute(text(
            "SELECT note_approval_id FROM note_unlocks WHERE visit_id = :v"), {"v": visit_id}).fetchall()
        assert len(unlocks) == 1

        actions = [row[0] for row in conn.execute(text(
            "SELECT action FROM audit_logs WHERE entity_id = :v ORDER BY at"), {"v": visit_id})]
        assert "visit.note_unlocked" in actions
        assert actions.count("visit.note_approved") == 2, "اعتماد أول + إعادة اعتماد بعد النقض"

        # تاريخ البوابة ① كله محفوظ: صفان، المنقوض منهما واحد
        approvals = conn.execute(text(
            "SELECT count(*) FROM note_approvals WHERE visit_id = :v"), {"v": visit_id}).scalar_one()
        assert approvals == 2

    # الإلحاقية حتى لمالك القاعدة (forbid_mutation)
    with owner_engine.connect() as conn:
        with pytest.raises(Exception, match="append-only"):
            conn.execute(text("UPDATE note_unlocks SET unlocked_at = now() WHERE visit_id = :v"),
                         {"v": visit_id})
    with owner_engine.connect() as conn:
        with pytest.raises(Exception, match="append-only"):
            conn.execute(text("DELETE FROM note_unlocks WHERE visit_id = :v"), {"v": visit_id})
