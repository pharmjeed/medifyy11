"""نقاط الأدمن: العيادات/الدكاترة/المقاعد/الفوترة/الترميز/الربط/الرفع الفاشل — FR-100..400."""
from __future__ import annotations

from sqlalchemy import text

from app.services.billing import sign_webhook_payload
from tests.conftest import auth


def test_clinics_crud_and_archive(client, admin_token):
    headers = auth(admin_token)
    created = client.post("/api/v1/clinics", headers=headers, json={"name": "عيادة الأنف والأذن"})
    assert created.status_code == 201
    clinic_id = created.json()["data"]["id"]

    updated = client.patch(f"/api/v1/clinics/{clinic_id}", headers=headers, json={"name": "عيادة الأنف والأذن والحنجرة"})
    assert updated.json()["data"]["name"] == "عيادة الأنف والأذن والحنجرة"

    archived = client.delete(f"/api/v1/clinics/{clinic_id}", headers=headers)
    assert archived.json()["data"]["archived"] is True

    names = [c["name"] for c in client.get("/api/v1/clinics", headers=headers).json()["data"]]
    assert "عيادة الأنف والأذن والحنجرة" not in names  # الأرشفة ناعمة وتخفيها من القائمة الافتراضية


def test_subscription_status_and_seats(client, admin_token):
    headers = auth(admin_token)
    status = client.get("/api/v1/subscription", headers=headers).json()["data"]
    assert status["seats_total"] == 6
    assert status["seats_used"] == 4  # 5 دكاترة منهم د. ريم معطلة
    assert status["seats_available"] == 2
    assert len(status["seat_events"]) >= 5


def test_seats_cannot_shrink_below_used(client, admin_token):
    response = client.patch("/api/v1/subscription/seats", headers=auth(admin_token), json={"seats_total": 2})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MDF-4221"


def test_create_doctor_consumes_seat_and_fails_when_exhausted(client, admin_token):
    headers = auth(admin_token)
    clinics = client.get("/api/v1/clinics", headers=headers).json()["data"]
    clinic_id = clinics[0]["id"]

    def new_doctor(index: int):
        return client.post("/api/v1/doctors", headers=headers, json={
            "full_name": f"د. اختبار المقاعد {index}",
            "username": f"dr.seat{index}",
            "password": "Doctor@12345",
            "specialty": "باطنة",
            "clinic_id": clinic_id,
        })

    first = new_doctor(1)
    assert first.status_code == 201
    second = new_doctor(2)
    assert second.status_code == 201
    third = new_doctor(3)  # المقاعد 6 والمستهلَك الآن 6
    assert third.status_code == 422
    assert third.json()["error"]["code"] == "MDF-4221"

    # التعطيل يحرر المقعد فوراً (FR-203)
    doctors = client.get("/api/v1/doctors", headers=headers, params={"per_page": 100}).json()["data"]
    seat1 = next(d for d in doctors if d["username"] == "dr.seat1")
    disabled = client.patch(f"/api/v1/doctors/{seat1['id']}", headers=headers, json={"is_active": False})
    assert disabled.status_code == 200
    fourth = new_doctor(4)
    assert fourth.status_code == 201

    # تنظيف: تعطيل دكاترة الاختبار
    doctors = client.get("/api/v1/doctors", headers=headers, params={"per_page": 100}).json()["data"]
    for doctor in doctors:
        if doctor["username"].startswith("dr.seat") and doctor["is_active"]:
            client.patch(f"/api/v1/doctors/{doctor['id']}", headers=headers, json={"is_active": False})

    notifications = client.get("/api/v1/notifications", headers=headers, params={"per_page": 100}).json()["data"]
    assert any(n["kind"] == "ad.seats_exhausted" for n in notifications)


def test_doctor_reset_password_returns_temp(client, admin_token):
    headers = auth(admin_token)
    doctors = client.get("/api/v1/doctors", headers=headers).json()["data"]
    khaled = next(d for d in doctors if d["username"] == "dr.khaled")
    response = client.post(f"/api/v1/doctors/{khaled['id']}/reset-password", headers=headers)
    temp = response.json()["data"]["temporary_password"]
    assert temp.startswith("Md-")
    login = client.post("/api/v1/auth/login", json={
        "facility": "1010456789", "username": "dr.khaled", "password": temp,
    })
    assert login.status_code == 200


def test_coding_systems_icd10am_locked(client, admin_token):
    headers = auth(admin_token)
    response = client.patch("/api/v1/settings/coding-systems", headers=headers,
                            json={"systems": {"ICD10AM": False}})
    assert response.status_code == 403

    toggled = client.patch("/api/v1/settings/coding-systems", headers=headers,
                           json={"systems": {"SBS": False}})
    assert toggled.status_code == 200
    client.patch("/api/v1/settings/coding-systems", headers=headers, json={"systems": {"SBS": True}})


def test_doctor_sees_active_coding_systems_only(client, doctor_token):
    response = client.get("/api/v1/settings/coding-systems", headers=auth(doctor_token))
    assert response.status_code == 200
    rows = response.json()["data"]
    assert {"ICD10AM", "ACHI", "SBS", "SFDA"} == {r["system"] for r in rows}
    assert all("is_active" not in r for r in rows)  # لا يرى إعدادات الإدارة


def test_integration_settings_and_test(client, admin_token):
    headers = auth(admin_token)
    config = client.get("/api/v1/settings/integration", headers=headers).json()["data"]
    assert config["endpoint_url"].startswith("https://his.alshifa")
    assert config["has_secret"] is True

    tested = client.post("/api/v1/settings/integration/test", headers=headers).json()["data"]
    assert tested["ok"] is True


def test_invoices_and_mock_payment_webhook_lifts_suspension(client, admin_token, owner_engine, doctor_token):
    headers = auth(admin_token)
    invoices = client.get("/api/v1/invoices", headers=headers).json()["data"]
    assert len(invoices) >= 4
    due = next(inv for inv in invoices if inv["status"] == "due")
    assert float(due["vat_sar"]) > 0  # VAT 15% مفصولة

    pay = client.post(f"/api/v1/invoices/{due['id']}/pay", headers=headers)
    assert pay.status_code == 200
    provider_ref = pay.json()["data"]["provider_ref"]

    # علّق المنشأة (محاكاة تعثر يوم 10 — DOC-09 §٢)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE facilities SET status = 'suspended' WHERE commercial_reg = '1010456789'"))

    # المنشأة معلقة → إنشاء زيارة يفشل بـ MDF-4013 (W-207)
    doctor_headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=doctor_headers).json()["data"]
    templates = client.get("/api/v1/templates", headers=doctor_headers).json()["data"]
    blocked = client.post("/api/v1/visits", headers=doctor_headers, json={
        "patient_id": patients[0]["id"], "template_id": templates[0]["id"],
    })
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "MDF-4013"

    # webhook موقّع بنتيجة السداد يرفع التعليق تلقائياً (FR-104/D-08)
    payload = {"provider_ref": provider_ref, "status": "paid"}
    unsigned = client.post("/api/v1/webhooks/payments", json=payload)
    assert unsigned.status_code == 403  # توقيع مفقود

    signed = client.post("/api/v1/webhooks/payments", json=payload,
                         headers={"X-Medify-Signature": sign_webhook_payload(payload)})
    assert signed.status_code == 200

    with owner_engine.connect() as conn:
        status = conn.execute(text(
            "SELECT status FROM facilities WHERE commercial_reg = '1010456789'"
        )).scalar_one()
    assert status == "active"

    allowed = client.post("/api/v1/visits", headers=doctor_headers, json={
        "patient_id": patients[0]["id"], "template_id": templates[0]["id"],
    })
    assert allowed.status_code == 201
    client.post(f"/api/v1/visits/{allowed.json()['data']['id']}/cancel", headers=doctor_headers)


def test_failed_uploads_metadata_only_and_retry(client, admin_token):
    headers = auth(admin_token)
    failed = client.get("/api/v1/uploads/failed", headers=headers).json()["data"]
    assert failed, "زيارة VIS-7A19 الفاشلة من seed"
    row = failed[0]
    assert set(row.keys()) == {"job_id", "visit_id", "doctor", "attempts_count", "error_code", "failed_at"}
    assert row["error_code"] == "MDF-5052"

    retried = client.post("/api/v1/uploads/retry", headers=headers, json={"job_ids": [row["job_id"]]})
    assert retried.status_code == 200
    assert retried.json()["data"]["results"][0]["ok"] is True  # الوجهة الوهمية تنجح الآن


def test_audit_log_records_admin_actions(client, admin_token):
    headers = auth(admin_token)
    logs = client.get("/api/v1/audit-logs", headers=headers, params={"per_page": 100}).json()["data"]
    actions = {log["action"] for log in logs}
    assert "uploads.bulk_retry" in actions
    assert "clinic.created" in actions
    assert any(log["actor"] != "النظام" for log in logs)


def test_notifications_center_w003(client, doctor_token):
    headers = auth(doctor_token)
    body = client.get("/api/v1/notifications", headers=headers).json()
    kinds = {n["kind"] for n in body["data"]}
    assert kinds <= {
        "dr.summary_ready", "dr.analysis_failed", "dr.upload_success", "dr.upload_failed",
        "dr.safety_flag", "dr.password_reset",
    }, "أحداث الدكتور حصراً من DOC-12"
    assert body["meta"]["unread"] >= 1
    unread = [n for n in body["data"] if n["read_at"] is None]
    marked = client.patch(f"/api/v1/notifications/{unread[0]['id']}/read", headers=headers)
    assert marked.status_code == 200
