"""المرحلة 16 — طابور «بانتظارك» + تقرير المدير الطبي.

معايير القبول: دخول in_review → يظهر فوراً بعمر صحيح | حسم آخر إرشاد → انتقال
تلقائي للمجموعة التالية | طبيب عادي يطلب التقرير → 403 | المُبطلة لا تظهر.
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
                       json={"duration_sec": 30}).status_code == 200
    return visit_id


def _group_of(queue: dict, visit_id: str) -> str | None:
    for name, rows in queue["groups"].items():
        if any(row["visit_id"] == visit_id for row in rows):
            return name
    return None


@pytest.fixture(scope="module")
def queue_patient(client, doctor_token) -> str:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900812", "display_name": "مريض الطابور"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def test_visit_appears_immediately_and_moves_between_groups(client, doctor_token, queue_patient):
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, queue_patient)

    queue = client.get("/api/v1/physicians/me/pending", headers=headers).json()["data"]
    assert _group_of(queue, visit_id) == "pending_guidance", "إرشادات معلّقة من P3"
    row = next(r for r in queue["groups"]["pending_guidance"] if r["visit_id"] == visit_id)
    assert row["age_hours"] >= 0 and row["age_hours"] < 1, "العمر صحيح ولحظي"
    assert row["pending_guidance_count"] > 0
    assert row["patient_mrn"] == "9900812"

    # حسم كل الإرشادات → المجموعة تتغير تلقائياً إلى in_review
    client.post(f"/api/v1/visits/{visit_id}/guidance/reject-remaining", headers=headers)
    queue = client.get("/api/v1/physicians/me/pending", headers=headers).json()["data"]
    assert _group_of(queue, visit_id) == "in_review"

    # البوابة ① → بانتظار البوابة ②
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    queue = client.get("/api/v1/physicians/me/pending", headers=headers).json()["data"]
    assert _group_of(queue, visit_id) == "awaiting_gate_two"


def test_voided_and_completed_visits_leave_the_queue(client, doctor_token, queue_patient):
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, queue_patient)
    queue = client.get("/api/v1/physicians/me/pending", headers=headers).json()["data"]
    assert _group_of(queue, visit_id) is not None

    assert client.post(f"/api/v1/visits/{visit_id}/void", headers=headers,
                       json={"reason": "duplicate"}).status_code == 200
    queue = client.get("/api/v1/physicians/me/pending", headers=headers).json()["data"]
    assert _group_of(queue, visit_id) is None, "المُبطلة لا تظهر"


def test_reopened_visit_lands_in_its_own_group(client, doctor_token, queue_patient):
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, queue_patient)
    client.post(f"/api/v1/visits/{visit_id}/guidance/reject-remaining", headers=headers)
    # قبول تشخيص واحد كي تمر جاهزية المطالبة
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    dx = next((item for section in summary["sections"] for item in section["guidance"]
               if item["kind"] in ("clinical_dx", "coding_match") and not item["requires_doctor_input"]), None)
    assert dx is not None
    client.patch(f"/api/v1/guidance-items/{dx['id']}", headers=headers, json={"status": "accepted"})
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers).status_code == 200

    queue = client.get("/api/v1/physicians/me/pending", headers=headers).json()["data"]
    assert _group_of(queue, visit_id) is None, "المنقولة خرجت من الطابور"

    assert client.post(f"/api/v1/visits/{visit_id}/reopen", headers=headers,
                       json={"reason": "استكمال"}).status_code == 200
    queue = client.get("/api/v1/physicians/me/pending", headers=headers).json()["data"]
    assert _group_of(queue, visit_id) == "reopened_not_uploaded"
    row = next(r for r in queue["groups"]["reopened_not_uploaded"] if r["visit_id"] == visit_id)
    assert row["version"] == 2


def test_admin_report_counts_only_and_doctor_forbidden(client, doctor_token, admin_token):
    forbidden = client.get("/api/v1/admin/pending-report", headers=auth(doctor_token))
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "MDF-4031"

    report = client.get("/api/v1/admin/pending-report", headers=auth(admin_token))
    assert report.status_code == 200, report.text
    data = report.json()["data"]
    assert isinstance(data["total_pending"], int)
    for row in data["physicians"]:
        assert set(row) == {"physician_id", "physician_name", "pending_count",
                            "avg_age_hours", "oldest_age_hours", "by_group"}
        assert isinstance(row["pending_count"], int)
        assert isinstance(row["avg_age_hours"], (int, float))
        # لا محتوى سريري: لا أسماء مرضى ولا نصوص مذكرات
        assert "patient" not in str(row).lower()


def test_daily_reminder_only_when_pending(client, doctor_token, queue_patient, owner_engine):
    """التذكير للأطباء ذوي المعلّق فقط — صفر معلّق = لا إشعار."""
    from sqlalchemy.orm import Session

    from app.services.pending_queue import send_daily_reminders

    headers = auth(doctor_token)
    _visit_in_review(client, headers, queue_patient)  # يضمن وجود معلّق واحد على الأقل

    with Session(owner_engine) as db:
        result = send_daily_reminders(db)
        db.commit()
    assert result["reminders_sent"] >= 1

    notifications = client.get("/api/v1/notifications", headers=headers,
                               params={"per_page": 50}).json()["data"]
    reminder = next((row for row in notifications
                     if (row.get("payload") or {}).get("reminder") == "pending_queue"), None)
    assert reminder is not None, "الإشعار وصل الطبيب"
    assert reminder["payload"]["pending_count"] >= 1
