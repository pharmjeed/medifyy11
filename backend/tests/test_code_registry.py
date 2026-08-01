"""السجل المرجعي للأكواد (قرار مالك 2026-08-02) — البحث، تحقق البايبلاين،
تحقق تعديل الدكتور، وبوابة الاعتماد ② المرجعية (MDF-4233)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import auth, record_consent


def _visit_to_review(client, headers) -> str:
    """زيارة كاملة حتى in_review — نفس رحلة test_visit_flow."""
    patients = client.get("/api/v1/patients", headers=headers, params={"query": "العتيبي"}).json()["data"]
    patient_id = patients[0]["id"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    template_id = next(t for t in templates if t["is_personal"])["id"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": template_id})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 60, "pauses_count": 0, "offline_chunks": 0})
    assert stopped.status_code == 200, stopped.text
    return visit_id


@pytest.fixture(scope="module")
def journey(client, doctor_token):
    headers = auth(doctor_token)
    return {"visit_id": _visit_to_review(client, headers), "headers": headers}


# ===== GET /codes/search =====

def test_search_requires_doctor_role(client, admin_token):
    assert client.get("/api/v1/codes/search", params={"system": "SBS", "q": "lipid"}).status_code == 401
    denied = client.get("/api/v1/codes/search", headers=auth(admin_token),
                        params={"system": "SBS", "q": "lipid"})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "MDF-4031"


def test_search_by_code_prefix_and_description(client, doctor_token):
    headers = auth(doctor_token)
    by_desc = client.get("/api/v1/codes/search", headers=headers,
                         params={"system": "SBS", "q": "lipid"}).json()
    assert any(row["code"] == "73000-00-60" for row in by_desc["data"])
    assert by_desc["meta"]["system_total"] >= 5

    by_code = client.get("/api/v1/codes/search", headers=headers,
                         params={"system": "SBS", "q": "73000"}).json()["data"]
    assert by_code and by_code[0]["code"] == "73000-00-60"


def test_search_normalizes_hyphens_and_ranks_active_first(client, doctor_token):
    headers = auth(doctor_token)
    # بلا شرطات — code_norm يطابق «730000060» مع «73000-00-60»
    rows = client.get("/api/v1/codes/search", headers=headers,
                      params={"system": "SBS", "q": "730000060"}).json()["data"]
    assert rows and rows[0]["code"] == "73000-00-60"

    rows = client.get("/api/v1/codes/search", headers=headers,
                      params={"system": "SBS", "q": "42845"}).json()["data"]
    assert rows[0]["code"] == "42845-01-01" and rows[0]["is_active"] is True
    retired = next(row for row in rows if row["code"] == "42845-00-02")
    assert retired["is_active"] is False
    assert retired["replaced_by"] == "42845-01-01"


# ===== تحقق البايبلاين: سجلنا مصدر الحقيقة لا ذاكرة النموذج =====

def test_pipeline_stamps_registry_provenance_from_our_registry(client, journey):
    summary = client.get(f"/api/v1/visits/{journey['visit_id']}/summary",
                         headers=journey["headers"]).json()["data"]
    guidance = [g for section in summary["sections"] for g in section["guidance"]]
    by_kind = {g["kind"]: g for g in guidance}

    # عيّنة P3 تدّعي «SBS 2026 release 1» — السجل يفرض إصداره الحقيقي SBS V2.0
    service = by_kind["clinical_service"]
    assert service["code_value"] == "73000-00-60"
    assert service["code_registry_version"] == "SBS V2.0"
    assert service["registry_status"] == "valid"

    dx = by_kind["clinical_dx"]
    assert dx["code_value"] == "I10"
    assert dx["code_registry_version"] == "ICD-10-AM 12th ed."
    assert dx["registry_status"] == "valid"

    # SFDA غير محمّل في السجل → unchecked: يمر كما ورد بلا حالة سجل
    rx = by_kind["clinical_rx"]
    assert rx["code_value"] is not None
    assert rx["registry_status"] is None


# ===== تحقق تعديل الدكتور (MDF-4233 فوري) =====

def test_modify_with_unknown_code_rejected(client, journey):
    summary = client.get(f"/api/v1/visits/{journey['visit_id']}/summary",
                         headers=journey["headers"]).json()["data"]
    pending = [g for section in summary["sections"] for g in section["guidance"]
               if g["status"] == "pending" and g["code_system"] == "ICD10AM"]
    item = pending[0]
    rejected = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=journey["headers"], json={
        "status": "modified",
        "modified_text": item["suggestion_text"],
        "modified_code_system": "ICD10AM",
        "modified_code_value": "ZZ99.99",
    })
    assert rejected.status_code == 422, rejected.text
    error = rejected.json()["error"]
    assert error["code"] == "MDF-4233"
    assert error["details"]["registry_status"] == "unknown"


def test_modify_with_inactive_code_rejected_with_replacement(client, journey):
    summary = client.get(f"/api/v1/visits/{journey['visit_id']}/summary",
                         headers=journey["headers"]).json()["data"]
    pending = [g for section in summary["sections"] for g in section["guidance"] if g["status"] == "pending"]
    item = pending[0]
    rejected = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=journey["headers"], json={
        "status": "modified",
        "modified_text": item["suggestion_text"],
        "modified_code_system": "SBS",
        "modified_code_value": "42845-00-02",
    })
    assert rejected.status_code == 422
    details = rejected.json()["error"]["details"]
    assert details["registry_status"] == "inactive"
    assert details["replaced_by"] == "42845-01-01"


def test_modify_with_valid_code_canonicalizes_and_stamps(client, journey):
    summary = client.get(f"/api/v1/visits/{journey['visit_id']}/summary",
                         headers=journey["headers"]).json()["data"]
    pending = [g for section in summary["sections"] for g in section["guidance"]
               if g["status"] == "pending" and g["code_system"] == "ICD10AM"]
    item = pending[0]
    # «e119» بلا نقطة وبحروف صغيرة → الصيغة القانونية E11.9 من السجل
    resolved = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=journey["headers"], json={
        "status": "modified",
        "modified_text": item["suggestion_text"] + " — clinician-entered",
        "modified_code_system": "ICD10AM",
        "modified_code_value": "e119",
    })
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["data"]["code_value"] == "E11.9"


# ===== البوابة ② المرجعية =====

def test_approve_blocked_on_inactive_code_then_recovers(client, doctor_token, owner_engine):
    headers = auth(doctor_token)
    visit_id = _visit_to_review(client, headers)
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    pending = [g for section in summary["sections"] for g in section["guidance"] if g["status"] == "pending"]

    target_id = None
    for index, item in enumerate(pending):
        if item["requires_doctor_input"]:
            resolved = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers, json={
                "status": "modified", "modified_text": item["suggestion_text"] + " — entered",
                "modified_code_system": "ICD10AM", "modified_code_value": "G44.2",
            })
            assert resolved.status_code == 200
        elif index == 0:
            assert client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                                json={"status": "accepted"}).status_code == 200
            target_id = item["id"]
        else:
            client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers, json={"status": "rejected"})
    assert target_id is not None

    # يُحاكى بند قديم اعتُمد بكود صار ملغى في V2.0 (تحديث سجل بعد الحسم) — كتابة مباشرة بدور المالك
    with owner_engine.connect() as conn:
        conn.execute(text(
            "UPDATE guidance_items SET code_system='SBS', code_value='42845-00-02', "
            "code_secondary_system=NULL, code_secondary_value=NULL WHERE id = :id"
        ), {"id": target_id})
        conn.commit()

    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    blocked = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert blocked.status_code == 422, blocked.text
    error = blocked.json()["error"]
    assert error["code"] == "MDF-4233"
    offending = error["details"]["items"]
    assert offending and offending[0]["code_value"] == "42845-00-02"
    assert offending[0]["registry_status"] == "inactive"
    assert offending[0]["replaced_by"] == "42845-01-01"

    # الدكتور يستبدل الكود الملغى ببديله النشط → الاعتماد يمر
    fixed = client.patch(f"/api/v1/guidance-items/{target_id}", headers=headers, json={
        "status": "modified", "modified_text": "Replaced retired code with its active mapping",
        "modified_code_system": "SBS", "modified_code_value": "42845-01-01",
    })
    assert fixed.status_code == 200, fixed.text
    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["approved"] is True
