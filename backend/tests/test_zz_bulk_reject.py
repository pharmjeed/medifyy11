"""المرحلة 13 — رفض المتبقي دفعة واحدة.

معايير القبول: N معلّقة → N أسطر Audit فردية بنفس bulk_action_id | صفر معلّق →
لا فعل (والواجهة لا تعرض الزر) | حسم آخر بند يحلّ شرط MDF-4222 فوراً.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth, record_consent


@pytest.fixture(scope="module")
def bulk_visit(client, doctor_token) -> dict:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900809", "display_name": "مريض الرفض الجماعي"})
    assert created.status_code == 201, created.text
    patient_id = created.json()["data"]["id"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    visit = client.post("/api/v1/visits", headers=headers,
                        json={"patient_id": patient_id, "template_id": templates[0]["id"]})
    assert visit.status_code == 201, visit.text
    visit_id = visit.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                       json={"duration_sec": 35}).status_code == 200
    return {"visit_id": visit_id, "headers": headers}


def test_bulk_reject_writes_individual_audit_rows_with_shared_id(client, bulk_visit, admin_token):
    headers = bulk_visit["headers"]
    visit_id = bulk_visit["visit_id"]

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    # نحسم واحداً بالقبول ليبقى المتبقي أقل من الإجمالي — الرفض الجماعي يمس المعلّق فقط
    first = next(item for section in summary["sections"] for item in section["guidance"]
                 if item["status"] == "pending" and not item["requires_doctor_input"])
    assert client.patch(f"/api/v1/guidance-items/{first['id']}", headers=headers,
                        json={"status": "accepted"}).status_code == 200

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    pending_before = summary["pending_guidance_count"]
    assert pending_before >= 2, "عيّنة P3 تترك أكثر من بند معلّق"

    result = client.post(f"/api/v1/visits/{visit_id}/guidance/reject-remaining", headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["rejected_count"] == pending_before
    bulk_id = data["bulk_action_id"]
    assert bulk_id

    # سطر تدقيق فردي لكل بند — بنفس معرّف الدفعة
    logs = client.get("/api/v1/audit-logs", headers=auth(admin_token),
                      params={"action": "guidance.rejected", "per_page": 100}).json()["data"]
    rows = [row for row in logs if row["meta"].get("bulk_action_id") == bulk_id]
    assert len(rows) == pending_before, "سطر مستقل لكل إرشاد لا سطر واحد للدفعة"
    assert len({row["entity_id"] for row in rows}) == pending_before, "كل سطر يخص بنداً مختلفاً"
    assert all(row["entity"] == "guidance_item" for row in rows)
    assert all(row["actor"] != "النظام" for row in rows), "الفاعل هوية بشرية"

    # الحالة انعكست فعلاً — لا معلّق بعدها
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    assert summary["pending_guidance_count"] == 0
    rejected = [item for section in summary["sections"] for item in section["guidance"]
                if item["status"] == "rejected"]
    assert len(rejected) == pending_before

    # شرط MDF-4222 انحل: البوابة ② لم تعد محجوبة بالإرشادات (تمر البوابة ① أولاً)
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text


def test_bulk_reject_with_zero_pending_is_noop(client, doctor_token, bulk_visit):
    """صفر معلّق → لا فعل ولا معرّف دفعة (الزر لا يظهر أصلاً في الواجهة)."""
    headers = bulk_visit["headers"]
    visit_id = bulk_visit["visit_id"]
    # الزيارة صارت معتمدة — نفس النقطة على زيارة أخرى بلا معلّق تعطي صفراً
    again = client.post(f"/api/v1/visits/{visit_id}/guidance/reject-remaining", headers=headers)
    assert again.status_code == 422, "بعد البوابة ② الحسم مغلق (MDF-4226)"
    assert again.json()["error"]["code"] == "MDF-4226"


def test_bulk_reject_noop_on_fresh_visit_without_pending(client, doctor_token):
    headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=headers).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patients[0]["id"], "template_id": templates[0]["id"]})
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers, json={"duration_sec": 20})

    first = client.post(f"/api/v1/visits/{visit_id}/guidance/reject-remaining", headers=headers)
    assert first.status_code == 200 and first.json()["data"]["rejected_count"] > 0
    second = client.post(f"/api/v1/visits/{visit_id}/guidance/reject-remaining", headers=headers)
    assert second.status_code == 200
    assert second.json()["data"] == {"rejected_count": 0, "bulk_action_id": None}
