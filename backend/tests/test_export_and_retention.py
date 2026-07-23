"""بنود المستوى A — التصدير (A3) وحذف الصوت المجدول (A4) وحارس التصدير قبل ② (A2)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text

from tests.conftest import auth, record_consent


def _approved_visit(client, doctor_token) -> str:
    """يبني زيارة كاملة حتى البوابة ② ويعيد معرّفها."""
    headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=headers, params={"query": "العتيبي"}).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    personal = [t for t in templates if t["is_personal"]]
    visit = client.post("/api/v1/visits", headers=headers, json={
        "patient_id": patients[0]["id"], "template_id": personal[0]["id"],
    }).json()["data"]
    visit_id = visit["id"]
    record_consent(client, visit_id, headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers, json={"duration_sec": 60})

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    for section in summary["sections"]:
        for item in section["guidance"]:
            if item["requires_doctor_input"]:
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers, json={
                    "status": "modified", "modified_text": item["suggestion_text"],
                    "modified_code_system": "ICD10AM", "modified_code_value": "R51",
                })
            else:
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                             json={"status": "accepted"})
    client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers)
    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    return visit_id


def test_export_blocked_before_gate_two(client, doctor_token):
    """A2/A3: لا تصدير قبل البوابة ② — MDF-4232."""
    headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=headers, params={"query": "العتيبي"}).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    personal = [t for t in templates if t["is_personal"]]
    visit = client.post("/api/v1/visits", headers=headers, json={
        "patient_id": patients[0]["id"], "template_id": personal[0]["id"],
    }).json()["data"]
    visit_id = visit["id"]
    record_consent(client, visit_id, headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers, json={"duration_sec": 30})

    for fmt in ("text", "pdf"):
        blocked = client.get(f"/api/v1/visits/{visit_id}/export/{fmt}", headers=headers)
        assert blocked.status_code == 422, blocked.text
        assert blocked.json()["error"]["code"] == "MDF-4232"


def test_export_text_after_gate_two(client, doctor_token):
    """A3/F-086: نص نظيف يُلصق في الـ EMR بعد البوابة ②."""
    visit_id = _approved_visit(client, doctor_token)
    headers = auth(doctor_token)
    response = client.get(f"/api/v1/visits/{visit_id}/export/text", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["format"] == "text"
    assert "SHA-256" in data["content"]  # بصمتا البوابتين مثبتتان في المخرج
    assert data["coded_items"] >= 1
    assert data["gate2_at"] is not None


def test_export_pdf_after_gate_two(client, doctor_token):
    """A3/F-038/F-084: PDF بترويسة ثنائية اللغة — ملف PDF فعلي."""
    visit_id = _approved_visit(client, doctor_token)
    headers = auth(doctor_token)
    response = client.get(f"/api/v1/visits/{visit_id}/export/pdf", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    body = response.content
    assert body.startswith(b"%PDF-"), "مخرج PDF صالح"
    assert len(body) > 2000
    assert 'filename="medify-note-' in response.headers.get("content-disposition", "")


def test_scheduled_purge_deletes_expired_audio(client, doctor_token, app_engine, owner_engine):
    """A4/F-071: منفّذ سياسة الاحتفاظ يحذف الصوت المنتهي ويختم deleted_at ويدوّن حدث تدقيق."""
    from app.services.retention import purge_expired_recordings

    visit_id = _approved_visit(client, doctor_token)

    # اجعل تسجيل هذه الزيارة منتهي الاحتفاظ (بدور المالك — يتجاوز RLS)
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE recordings SET retention_until = :past WHERE visit_id = :vid"),
            {"past": past, "vid": visit_id},
        )
        before = conn.execute(
            text("SELECT deleted_at FROM recordings WHERE visit_id = :vid"), {"vid": visit_id}
        ).scalar_one()
        assert before is None

    from sqlalchemy.orm import Session
    with Session(owner_engine) as db:
        result = purge_expired_recordings(db)
        db.commit()
    assert result["purged"] >= 1

    with owner_engine.begin() as conn:
        after = conn.execute(
            text("SELECT deleted_at FROM recordings WHERE visit_id = :vid"), {"vid": visit_id}
        ).scalar_one()
        assert after is not None, "deleted_at خُتم"
        audit_count = conn.execute(
            text("SELECT count(*) FROM audit_logs WHERE action = 'recording.purged' "
                 "AND entity_id IN (SELECT id::text FROM recordings WHERE visit_id = :vid)"),
            {"vid": visit_id},
        ).scalar_one()
        assert audit_count >= 1, "حدث تدقيق لكل عملية حذف"

    # idempotent: تشغيل ثانٍ لا يحذف شيئاً
    with Session(owner_engine) as db:
        again = purge_expired_recordings(db)
        db.commit()
    assert again["purged"] == 0
