"""المرحلة 7 — Idempotency واعٍ بالنسخة + إيصالات التسليم.

معايير القبول: إرسال ناجح + ضياع الرد + retry = كتابة واحدة فعلية | v2 = إرسال
جديد بمفتاح جديد | عطل بعد الإيصال → retry يرجع من الإيصال بلا إرسال.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.conftest import auth, record_consent


def _visit_uploaded(client, headers, patient_id: str) -> str:
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers, json={"duration_sec": 25})
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    for section in summary["sections"]:
        for item in section["guidance"]:
            if item["status"] != "pending":
                continue
            # م12: التشخيص يُقبل (MDS يتطلب تشخيصاً أولياً) والباقي يُرفض
            if item["kind"] in ("clinical_dx", "coding_match") and not item["requires_doctor_input"]:
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                             json={"status": "accepted"})
            else:
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                             json={"status": "rejected"})
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    return visit_id


@pytest.fixture(scope="module")
def idem_patient(client, doctor_token) -> str:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900806", "display_name": "مريض الإيصالات"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def test_successful_upload_writes_receipt_with_version_key(client, doctor_token, idem_patient, owner_engine):
    headers = auth(doctor_token)
    visit_id = _visit_uploaded(client, headers, idem_patient)
    with owner_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT idempotency_key, target_system, response_hash FROM delivery_receipts "
            "WHERE idempotency_key = :key"
        ), {"key": f"{visit_id}:1"}).fetchall()
    assert len(rows) == 1
    assert rows[0].target_system == "mock" and rows[0].response_hash


def test_crash_after_receipt_retry_replays_without_sending(client, doctor_token, admin_token,
                                                           idem_patient, owner_engine):
    """انهيار بعد الإيصال وقبل تحديث المهمة: retry يرجع النجاح من الإيصال بلا إرسال.

    البرهان: الوجهة مضبوطة على الفشل الدائم — لو أُرسل فعلاً لفشل؛ النجاح يثبت
    أن الرد جاء من الإيصال.
    """
    headers = auth(doctor_token)
    admin_headers = auth(admin_token)
    assert client.patch("/api/v1/settings/integration", headers=admin_headers,
                        json={"endpoint_url": "https://his.example/fail-unreachable"}).status_code == 200
    try:
        templates = client.get("/api/v1/templates", headers=headers).json()["data"]
        created = client.post("/api/v1/visits", headers=headers,
                              json={"patient_id": idem_patient, "template_id": templates[0]["id"]})
        visit_id = created.json()["data"]["id"]
        record_consent(client, visit_id, headers)
        client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
        client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers, json={"duration_sec": 20})
        summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
        for section in summary["sections"]:
            for item in section["guidance"]:
                if item["status"] != "pending":
                    continue
                # م12: التشخيص يُقبل (MDS يتطلب تشخيصاً أولياً) والباقي يُرفض
                if item["kind"] in ("clinical_dx", "coding_match") and not item["requires_doctor_input"]:
                    client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                                 json={"status": "accepted"})
                else:
                    client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                                 json={"status": "rejected"})
        assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
        approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
        assert approved.status_code == 200
        assert approved.json()["data"]["upload"]["status"] == "failed", "الوجهة الفاشلة أفشلت الرفع"

        # محاكاة «التسليم وصل والإيصال كُتب ثم انهار الخادم قبل تحديث المهمة»:
        # إيصال يُزرع يدوياً بنفس المفتاح/الوجهة — والوجهة ما تزال فاشلة
        with owner_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO delivery_receipts (id, facility_id, idempotency_key, target_system, "
                "delivered_at, response_hash, created_at, updated_at) "
                "SELECT gen_random_uuid(), facility_id, :key, 'mock', now(), 'seeded-ack', now(), now() "
                "FROM visits WHERE id = :visit"
            ), {"key": f"{visit_id}:1", "visit": visit_id})

        retried = client.post(f"/api/v1/visits/{visit_id}/upload-retry", headers=headers)
        assert retried.status_code == 200, retried.text
        assert retried.json()["data"]["status"] == "confirmed", "النجاح من الإيصال — لا إرسال فعلي"

        summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
        assert summary["state"] == "uploaded"
        assert summary["versions"][0]["upload_status"] == "uploaded"

        logs = client.get("/api/v1/audit-logs", headers=admin_headers,
                          params={"action": "upload.confirmed", "per_page": 100}).json()["data"]
        entry = next(row for row in logs if row["meta"].get("replayed_from_receipt"))
        assert entry is not None
    finally:
        client.patch("/api/v1/settings/integration", headers=admin_headers,
                     json={"endpoint_url": ""})


def test_new_version_means_new_key_and_new_send(client, doctor_token, idem_patient, owner_engine):
    headers = auth(doctor_token)
    visit_id = _visit_uploaded(client, headers, idem_patient)
    assert client.post(f"/api/v1/visits/{visit_id}/reopen", headers=headers,
                       json={"reason": "استكمال"}).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text

    with owner_engine.connect() as conn:
        keys = {row.idempotency_key for row in conn.execute(text(
            "SELECT idempotency_key FROM delivery_receipts WHERE idempotency_key LIKE :prefix"
        ), {"prefix": f"{visit_id}:%"})}
        job_keys = {row.idempotency_key for row in conn.execute(text(
            "SELECT idempotency_key FROM upload_jobs WHERE visit_id = :id"
        ), {"id": visit_id})}
    assert keys == {f"{visit_id}:1", f"{visit_id}:2"}, "نسخة جديدة = مفتاح وإرسال جديدان"
    assert job_keys == {f"{visit_id}:1", f"{visit_id}:2"}


def test_duplicate_idempotency_key_rejected_by_db(client, doctor_token, idem_patient, owner_engine):
    headers = auth(doctor_token)
    visit_id = _visit_uploaded(client, headers, idem_patient)
    with owner_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT facility_id, approval_id FROM upload_jobs WHERE visit_id = :id"
        ), {"id": visit_id}).fetchone()
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(text(
                    "INSERT INTO upload_jobs (id, visit_id, facility_id, approval_id, idempotency_key, "
                    "status, attempts_count, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :v, :f, :a, :key, 'queued', 0, now(), now())"
                ), {"v": visit_id, "f": row.facility_id, "a": row.approval_id, "key": f"{visit_id}:1"})