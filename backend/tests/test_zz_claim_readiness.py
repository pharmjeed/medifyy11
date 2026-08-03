"""المرحلة 12 — محرك جاهزية المطالبة: قواعد YAML بيانات لا كوداً.

معايير القبول: إجراء بلا ربط → block ثم الربط → يمر | MDS ناقص → block بالحقل |
قاعدة YAML جديدة تعمل بلا deploy.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.conftest import auth, record_consent

RULES_DIR = Path(__file__).resolve().parents[1] / "rules"


def _visit_in_review(client, headers, patient_id: str) -> str:
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                       json={"duration_sec": 35}).status_code == 200
    return visit_id


def _resolve_all(client, headers, visit_id: str, *, accept_kinds: tuple[str, ...] = ()) -> None:
    """يقبل الأنواع المطلوبة ويرفض الباقي — المحجوب دون العتبة يُعطى كوداً بوعي."""
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    for section in summary["sections"]:
        for item in section["guidance"]:
            if item["status"] != "pending":
                continue
            if item["kind"] in accept_kinds:
                if item["requires_doctor_input"]:
                    response = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers, json={
                        "status": "modified",
                        "modified_text": item["suggestion_text"],
                        "modified_code_system": "ICD10AM",
                        "modified_code_value": "G44.2",
                    })
                else:
                    response = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                                            json={"status": "accepted"})
            else:
                response = client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                                        json={"status": "rejected"})
            assert response.status_code == 200, response.text


@pytest.fixture(scope="module")
def claim_patient(client, doctor_token) -> str:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900808", "display_name": "مريض جاهزية المطالبة"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def test_procedure_without_link_blocks_then_link_passes(client, doctor_token, claim_patient):
    """قاعدة (1): خدمة معتمدة بلا ربط تشخيص → block يمنع الاعتماد؛ الربط يرفعه."""
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, claim_patient)
    # نقبل التشخيص والخدمة معاً — الخدمة في العيّنة تأتي مربوطة، فنفكّ ربطها لاختبار القاعدة
    _resolve_all(client, headers, visit_id, accept_kinds=("clinical_dx", "clinical_service"))

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    service = next(item for section in summary["sections"] for item in section["guidance"]
                   if item["kind"] == "clinical_service" and item["status"] in ("accepted", "modified"))
    # فكّ الربط عبر إعادة الحسم بالتعديل (يمسح linked_dx_code منطقياً بإعادة ضبطه لاحقاً)
    from app.db import system_session
    from app.models import GuidanceItem

    with system_session() as sdb:
        row = sdb.get(GuidanceItem, uuid.UUID(service["id"]))
        row.linked_dx_code = None

    readiness = client.get(f"/api/v1/visits/{visit_id}/claim-readiness", headers=headers).json()["data"]
    assert readiness["ready"] is False
    blocking = [f for f in readiness["findings"] if f["severity"] == "block"]
    assert any(f["rule_id"] == "MEDICAL_NECESSITY_LINK" for f in blocking)
    assert readiness["unlinked_items"], "واجهة الربط تعرف البند غير المربوط"
    assert readiness["diagnosis_options"], "خيارات التشخيص متاحة للربط"

    # البوابة ① أولاً — فحص جاهزية المطالبة يقع داخل البوابة ② بعدها
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    blocked = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "MDF-4237"

    # الربط عبر النقطة المخصصة → القاعدة تمر والاعتماد يمضي
    dx_code = readiness["diagnosis_options"][0]["code_value"]
    linked = client.patch(f"/api/v1/guidance-items/{service['id']}/link-diagnosis",
                          headers=headers, json={"linked_dx_code": dx_code})
    assert linked.status_code == 200, linked.text
    assert linked.json()["data"]["claim_readiness"]["ready"] is True

    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text


def test_link_rejects_code_outside_visit_diagnoses(client, doctor_token, claim_patient):
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, claim_patient)
    _resolve_all(client, headers, visit_id, accept_kinds=("clinical_dx", "clinical_service"))
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    service = next(item for section in summary["sections"] for item in section["guidance"]
                   if item["kind"] == "clinical_service" and item["status"] in ("accepted", "modified"))
    bad = client.patch(f"/api/v1/guidance-items/{service['id']}/link-diagnosis",
                       headers=headers, json={"linked_dx_code": "Z99.9"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "MDF-4233"


def test_mds_missing_field_blocks_with_field_name(client, doctor_token, claim_patient, owner_engine):
    """قاعدة (2): حقل MDS ناقص → block يسمّي الحقل."""
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, claim_patient)
    _resolve_all(client, headers, visit_id)  # رفض الكل → لا تشخيص أولي

    readiness = client.get(f"/api/v1/visits/{visit_id}/claim-readiness", headers=headers).json()["data"]
    blocking = [f for f in readiness["findings"] if f["severity"] == "block"]
    mds = [f for f in blocking if f["rule_id"] == "NPHIES_MDS_REQUIRED_FIELDS"]
    assert mds, "الحقل الناقص يُبلَّغ عنه"
    assert mds[0]["related_codes"] == ["primary_diagnosis"]
    assert "تشخيص" in mds[0]["message_ar"]

    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    blocked = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "MDF-4237"


def test_new_yaml_rule_works_without_deploy(client, doctor_token, claim_patient):
    """قاعدة YAML جديدة تُقرأ فور كتابتها — بلا إعادة تشغيل ولا نشر."""
    headers = auth(doctor_token)
    visit_id = _visit_in_review(client, headers, claim_patient)
    _resolve_all(client, headers, visit_id, accept_kinds=("clinical_dx",))

    before = client.get(f"/api/v1/visits/{visit_id}/claim-readiness", headers=headers).json()["data"]
    assert not any(f["rule_id"] == "TEST_RUNTIME_RULE" for f in before["findings"])

    new_rule = RULES_DIR / "zz_test_runtime.yaml"
    new_rule.write_text(
        "- rule_id: TEST_RUNTIME_RULE\n"
        "  type: prior_auth\n"
        "  severity: warn\n"
        "  message_ar: \"قاعدة اختبار وقت التشغيل\"\n"
        "  params:\n"
        "    codes: [I10]\n",
        encoding="utf-8",
    )
    try:
        after = client.get(f"/api/v1/visits/{visit_id}/claim-readiness", headers=headers).json()["data"]
        finding = next(f for f in after["findings"] if f["rule_id"] == "TEST_RUNTIME_RULE")
        assert finding["severity"] == "warn"
        assert finding["related_codes"], "الكود المطابق مذكور"
        assert after["ready"] is True, "التحذير لا يحجب"
    finally:
        new_rule.unlink(missing_ok=True)


def test_code_composition_rules_evaluate_from_yaml():
    """قاعدة (3) تُقيَّم من البيانات — بلا استدعاء قاعدة بيانات."""
    from types import SimpleNamespace

    from app.services.claim_readiness import _eval_composition

    def _item(kind: str, code: str, system: str = "ICD10AM") -> SimpleNamespace:
        return SimpleNamespace(kind=kind, code_value=code, code_system=system,
                               linked_dx_code=None, suggestion_text="")

    manifestation_rule = {
        "rule_id": "MANIFESTATION_REQUIRES_UNDERLYING", "type": "code_composition",
        "severity": "block", "message_ar": "…",
        "params": {"manifestation_requires": [
            {"code": "H36.0", "requires_any": ["E10", "E11"], "message_ar": "يتطلب نوع السكري"},
        ]},
    }
    lonely = _eval_composition(manifestation_rule, [_item("clinical_dx", "H36.0")], {})
    assert lonely[0].severity == "block"
    with_underlying = _eval_composition(
        manifestation_rule, [_item("clinical_dx", "H36.0"), _item("clinical_dx", "E11.9")], {})
    assert with_underlying[0].severity == "pass"

    primary_rule = {
        "rule_id": "NOT_VALID_PRIMARY_DIAGNOSIS", "type": "code_composition",
        "severity": "block", "message_ar": "…",
        "params": {"not_primary_diagnosis": ["Z00.0", "R51"]},
    }
    only_banned = _eval_composition(primary_rule, [_item("clinical_dx", "R51")], {})
    assert only_banned[0].severity == "block"
    # وجود تشخيص صالح آخر يرفع الحجب — الممنوع ثانوي عندئذ
    with_valid = _eval_composition(
        primary_rule, [_item("clinical_dx", "R51"), _item("clinical_dx", "I10")], {})
    assert with_valid[0].severity == "pass"
