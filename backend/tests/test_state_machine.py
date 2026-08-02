"""المرحلة 1 — توسعة آلة الحالات: reopened + مصادر voided الموسّعة + Audit لكل انتقال.

معايير القبول:
- انتقال غير شرعي → 409 بكود MDF-4223 (تطبيقياً وعلى مستوى trigger القاعدة).
- كل انتقال ناجح يكتب سطر Audit موحّداً visit.state_changed (من/إلى + الفاعل).
- المسار الجديد: uploaded → reopened → in_review (أساس دورة النسخ — المرحلة 6).
- مصادر الإبطال الموسّعة: summarized وapproved قبل النقل (المرحلة 4).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import auth, record_consent


def _patient(client, headers, mrn: str) -> str:
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": mrn, "display_name": "مريض آلة الحالات"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def _visit_in_review(client, headers, patient_id: str) -> str:
    """رحلة كاملة حتى in_review — نفس نمط test_visit_flow."""
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 30})
    assert stopped.status_code == 200, stopped.text
    return visit_id


def _visit_uploaded(client, headers, patient_id: str) -> str:
    """حتى uploaded: حسم الإرشادات بالرفض ثم البوابتان — المحرك الوهمي يؤكد الرفع فوراً."""
    visit_id = _visit_in_review(client, headers, patient_id)
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    for section in summary["sections"]:
        for item in section["guidance"]:
            if item["status"] == "pending":
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                             json={"status": "rejected"})
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["upload"]["status"] == "confirmed"
    return visit_id


@pytest.fixture(scope="module")
def sm_patient(client, doctor_token) -> str:
    return _patient(client, auth(doctor_token), "9900801")


def test_illegal_transition_rejected_409_at_api(client, doctor_token, sm_patient):
    """إبطال زيارة منقولة → 409 MDF-4223 — «من uploaded وما بعدها» مرفوض."""
    headers = auth(doctor_token)
    visit_id = _visit_uploaded(client, headers, sm_patient)
    blocked = client.post(f"/api/v1/visits/{visit_id}/void", headers=headers,
                          json={"reason": "duplicate"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "MDF-4223"


def test_reopen_cycle_allowed_at_db_level(client, doctor_token, sm_patient, owner_engine):
    """uploaded → reopened → in_review شرعي — وreopened → approved قفزة مرفوضة."""
    headers = auth(doctor_token)
    visit_id = _visit_uploaded(client, headers, sm_patient)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE visits SET state = 'reopened' WHERE id = :id"), {"id": visit_id})
    with owner_engine.connect() as conn:
        # قفزة تتجاوز البوابتين مرفوضة من trigger القاعدة نفسها
        with pytest.raises(DBAPIError, match="MDF-4223"):
            with conn.begin_nested():
                conn.execute(text("UPDATE visits SET state = 'approved' WHERE id = :id"), {"id": visit_id})
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE visits SET state = 'in_review' WHERE id = :id"), {"id": visit_id})
        state = conn.execute(text("SELECT state FROM visits WHERE id = :id"), {"id": visit_id}).scalar_one()
    assert state == "in_review"


def test_void_sources_summarized_and_approved_at_db_level(client, doctor_token, sm_patient, owner_engine):
    """توسعة 0011: summarized → voided وapproved → voided شرعيان (مواصفة المرحلة 4)."""
    headers = auth(doctor_token)
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]

    def _consented_draft() -> str:
        created = client.post("/api/v1/visits", headers=headers,
                              json={"patient_id": sm_patient, "template_id": templates[0]["id"]})
        assert created.status_code == 201, created.text
        visit_id = created.json()["data"]["id"]
        record_consent(client, visit_id, headers)
        return visit_id

    # مشي مملوك للقاعدة حتى summarized ثم إبطال — الموافقة موثّقة فيمرّ draft→recording
    v1 = _consented_draft()
    with owner_engine.begin() as conn:
        for state in ("recording", "transcribed", "summarized", "voided"):
            conn.execute(text("UPDATE visits SET state = :s WHERE id = :id"), {"s": state, "id": v1})
        assert conn.execute(text("SELECT state FROM visits WHERE id = :id"), {"id": v1}).scalar_one() == "voided"

    # وحتى approved ثم إبطال (قبل النقل)
    v2 = _consented_draft()
    with owner_engine.begin() as conn:
        for state in ("recording", "transcribed", "summarized", "in_review", "approved", "voided"):
            conn.execute(text("UPDATE visits SET state = :s WHERE id = :id"), {"s": state, "id": v2})
        assert conn.execute(text("SELECT state FROM visits WHERE id = :id"), {"id": v2}).scalar_one() == "voided"


def test_upload_failed_is_not_a_void_source(client, doctor_token, sm_patient, owner_engine):
    """المواصفة تحصر مصادر الإبطال الأربعة — upload_failed خارجها (مساره retry ثم reopen)."""
    headers = auth(doctor_token)
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": sm_patient, "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    with owner_engine.begin() as conn:
        for state in ("recording", "transcribed", "summarized", "in_review", "approved", "upload_failed"):
            conn.execute(text("UPDATE visits SET state = :s WHERE id = :id"), {"s": state, "id": visit_id})
    with owner_engine.connect() as conn:
        with pytest.raises(DBAPIError, match="MDF-4223"):
            with conn.begin_nested():
                conn.execute(text("UPDATE visits SET state = 'voided' WHERE id = :id"), {"id": visit_id})


def test_every_transition_writes_unified_audit(client, doctor_token, admin_token, sm_patient):
    """رحلة كاملة → ستة أسطر visit.state_changed بالترتيب، بفاعل بشري إلا الرفع (النظام)."""
    headers = auth(doctor_token)
    visit_id = _visit_uploaded(client, headers, sm_patient)

    # جمع أسطر الزيارة عبر الصفحات (سقف per_page=100 والحزمة كلها تكتب انتقالات)
    rows: list[dict] = []
    page = 1
    while True:
        response = client.get("/api/v1/audit-logs", headers=auth(admin_token),
                              params={"action": "visit.state_changed", "per_page": 100, "page": page}).json()
        batch = response["data"]
        rows.extend(row for row in batch if row["entity_id"] == visit_id)
        if len(batch) < 100:
            break
        page += 1
    # id هو UUID v7 (uuid6 يضمن الرتابة داخل العملية) — الفرز به = الترتيب الزمني الحقيقي
    rows.sort(key=lambda r: r["id"])
    hops = [(row["meta"]["from"], row["meta"]["to"], row["actor"]) for row in rows]
    expected = [
        ("draft", "recording"),
        ("recording", "transcribed"),
        ("transcribed", "summarized"),
        ("summarized", "in_review"),
        ("in_review", "approved"),
        ("approved", "uploaded"),
    ]
    assert [(h[0], h[1]) for h in hops] == expected, hops
    # الانتقالات بفعل الدكتور تحمل هويته؛ نتيجة الرفع فعل النظام
    for from_state, _to, actor in hops:
        if from_state == "approved":
            assert actor == "النظام"
        else:
            assert actor != "النظام"
