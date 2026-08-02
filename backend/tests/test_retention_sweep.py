"""المرحلة 8 — سياسة الاحتفاظ الموحّدة: legal_hold + النسخ المنقولة + السياسات القابلة للتعديل.

معايير القبول: صوت متقادم يُحذف مع Audit (في test_export_and_retention المحدَّث) |
legal_hold لا يُحذف منه شيء | لقطة منقولة داخل مدتها لا تُمس.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

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
            if item["status"] == "pending":
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                             json={"status": "rejected"})
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers).status_code == 200
    return visit_id


@pytest.fixture(scope="module")
def ret_patient(client, doctor_token) -> str:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900807", "display_name": "مريض الاحتفاظ"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def _sweep(owner_engine, now: dt.datetime) -> None:
    from app.services.retention import sweep_retention

    with Session(owner_engine) as db:
        sweep_retention(db, now=now)
        db.commit()


def test_legal_hold_freezes_all_retention(client, doctor_token, admin_token, ret_patient, owner_engine):
    """legal_hold: لا soft ولا hard لأي أثر ما دام مرفوعاً — وفكّه يعيد السريان."""
    headers = auth(doctor_token)
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": ret_patient, "template_id": templates[0]["id"]})
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers, json={"duration_sec": 20})

    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE recordings SET retention_until = :p WHERE visit_id = :v"),
                     {"p": past, "v": visit_id})
        conn.execute(text("UPDATE transcripts SET created_at = :p WHERE visit_id = :v"),
                     {"p": past - dt.timedelta(days=120), "v": visit_id})

    held = client.post(f"/api/v1/visits/{visit_id}/legal-hold", headers=auth(admin_token),
                       json={"enabled": True})
    assert held.status_code == 200 and held.json()["data"]["legal_hold"] is True

    now = dt.datetime.now(dt.timezone.utc)
    _sweep(owner_engine, now)
    with owner_engine.begin() as conn:
        rec = conn.execute(text("SELECT deleted_at FROM recordings WHERE visit_id = :v"),
                           {"v": visit_id}).scalar_one()
        tr = conn.execute(text("SELECT deleted_at FROM transcripts WHERE visit_id = :v"),
                          {"v": visit_id}).scalar_one()
    assert rec is None and tr is None, "legal_hold جمّد كل شيء"

    # فكّ التجميد → السريان يعود
    client.post(f"/api/v1/visits/{visit_id}/legal-hold", headers=auth(admin_token),
                json={"enabled": False})
    _sweep(owner_engine, now)
    with owner_engine.begin() as conn:
        rec = conn.execute(text("SELECT deleted_at FROM recordings WHERE visit_id = :v"),
                           {"v": visit_id}).scalar_one()
        tr = conn.execute(text("SELECT deleted_at FROM transcripts WHERE visit_id = :v"),
                          {"v": visit_id}).scalar_one()
    assert rec is not None and tr is not None


def test_uploaded_snapshot_within_period_untouched_and_purged_after(client, doctor_token,
                                                                    ret_patient, owner_engine):
    """اللقطة المنقولة داخل مدتها لا تُمس؛ وبعد المدة تُحذف عبر صمام الاحتفاظ حصراً."""
    headers = auth(doctor_token)
    visit_id = _visit_uploaded(client, headers, ret_patient)
    now = dt.datetime.now(dt.timezone.utc)

    _sweep(owner_engine, now)
    with owner_engine.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM note_versions WHERE visit_id = :v"),
                             {"v": visit_id}).scalar_one()
    assert count == 1, "داخل المدة (365) — لا مساس"

    # تقادم مفتعل: تعطيل مؤقت لقفل الجمود (سقالة اختبار بدور المالك) لتبديل uploaded_at
    with owner_engine.begin() as conn:
        conn.execute(text("ALTER TABLE note_versions DISABLE TRIGGER trg_note_versions_immutable"))
        conn.execute(text("UPDATE note_versions SET uploaded_at = :old WHERE visit_id = :v"),
                     {"old": now - dt.timedelta(days=400), "v": visit_id})
        conn.execute(text("ALTER TABLE note_versions ENABLE TRIGGER trg_note_versions_immutable"))

    # بدون الصمام: الحذف مرفوض حتى للمالك
    with owner_engine.connect() as conn:
        with pytest.raises(Exception, match="append-only"):
            conn.execute(text("DELETE FROM note_versions WHERE visit_id = :v"), {"v": visit_id})

    _sweep(owner_engine, now)
    with owner_engine.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM note_versions WHERE visit_id = :v"),
                             {"v": visit_id}).scalar_one()
        audits = conn.execute(text(
            "SELECT count(*) FROM audit_logs WHERE action = 'retention.hard_deleted' "
            "AND meta_json->>'artifact_type' = 'note_versions_uploaded'"
        )).scalar_one()
    assert count == 0, "بعد المدة + السماح — حُذفت عبر الصمام"
    assert audits >= 1, "الحذف مدوَّن (نوع + عدد، بلا محتوى)"


def test_retention_policies_endpoints(client, doctor_token, admin_token):
    """السياسات الافتراضية + تجاوز المنشأة + retention-status — أعداد فقط وRBAC أدمن."""
    admin_headers = auth(admin_token)
    current = client.get("/api/v1/settings/retention", headers=admin_headers).json()["data"]
    assert current["policies"]["audio"] == 90
    assert current["policies"]["aggregated_metrics"] is None
    assert current["grace_days"] == 7

    patched = client.patch("/api/v1/settings/retention", headers=admin_headers,
                           json={"artifact_type": "audio", "retention_days": 45})
    assert patched.status_code == 200
    assert patched.json()["data"]["policies"]["audio"] == 45

    bad = client.patch("/api/v1/settings/retention", headers=admin_headers,
                       json={"artifact_type": "everything", "retention_days": 1})
    assert bad.status_code == 404

    status = client.get("/api/v1/admin/retention-status", headers=admin_headers).json()["data"]
    assert isinstance(status["audio"]["due_within_7d"], int)
    assert isinstance(status["legal_hold_visits"], int)

    # دكتور → 403 على نقاط الأدمن
    forbidden = client.get("/api/v1/admin/retention-status", headers=auth(doctor_token))
    assert forbidden.status_code == 403

    # إرجاع الافتراضي (بلا تلويث بقية الحزمة)
    client.patch("/api/v1/settings/retention", headers=admin_headers,
                 json={"artifact_type": "audio", "retention_days": 90})


def test_voided_visit_follows_shortest_period(client, doctor_token, ret_patient, owner_engine):
    """المُبطلة تتبع أقصر مدة (intermediate=30) — صوتها يوسم قبل مدته الاعتيادية."""
    headers = auth(doctor_token)
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": ret_patient, "template_id": templates[0]["id"]})
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers, json={"duration_sec": 20})
    assert client.post(f"/api/v1/visits/{visit_id}/void", headers=headers,
                       json={"reason": "test_recording"}).status_code == 200

    now = dt.datetime.now(dt.timezone.utc)
    # عمر 40 يوماً ومدة اعتيادية بعيدة (+50) — الأقصر (30) يسري لأنها مُبطلة
    with owner_engine.begin() as conn:
        conn.execute(text(
            "UPDATE recordings SET created_at = :c, retention_until = :r WHERE visit_id = :v"
        ), {"c": now - dt.timedelta(days=40), "r": now + dt.timedelta(days=50), "v": visit_id})

    _sweep(owner_engine, now)
    with owner_engine.begin() as conn:
        marked = conn.execute(text("SELECT deleted_at FROM recordings WHERE visit_id = :v"),
                              {"v": visit_id}).scalar_one()
    assert marked is not None, "أقصر مدة سرت على المُبطلة"
