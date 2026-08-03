"""المرحلة 17 — سحب سياق المريض من HIS خلف feature flag (ضد mock FHIR server).

معايير القبول: سياق متاح → اللوحة + وصوله لـP2/P3 | HIS ساقط → لا تعطيل + العلم
مضبوط | لا PHI من السياق في أي log.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pytest
from sqlalchemy import text

from tests.conftest import auth

ALLERGY_TEXT = "Penicillin allergy"
CONDITION_TEXT = "Type 2 diabetes mellitus"
MEDICATION_TEXT = "Metformin 500mg"


class _FhirHandler(BaseHTTPRequestHandler):
    """mock FHIR server — Patient/Condition/MedicationRequest/AllergyIntolerance."""

    def log_message(self, *args):  # صمت في مخرجات الاختبار
        return

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]
        if path == "Patient":
            self._send({"resourceType": "Bundle", "entry": [
                {"resource": {"resourceType": "Patient", "id": "p-1",
                              "gender": "male", "birthDate": "1980-05-01"}}]})
        elif path == "Condition":
            self._send({"resourceType": "Bundle", "entry": [
                {"resource": {"resourceType": "Condition", "code": {"text": CONDITION_TEXT}}}]})
        elif path == "MedicationRequest":
            self._send({"resourceType": "Bundle", "entry": [
                {"resource": {"resourceType": "MedicationRequest",
                              "medicationCodeableConcept": {"text": MEDICATION_TEXT}}}]})
        elif path == "AllergyIntolerance":
            self._send({"resourceType": "Bundle", "entry": [
                {"resource": {"resourceType": "AllergyIntolerance", "code": {"text": ALLERGY_TEXT}}}]})
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture()
def fhir_server():
    server = HTTPServer(("127.0.0.1", 0), _FhirHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def his_enabled(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "his_context_enabled", True, raising=False)
    yield
    monkeypatch.setattr(settings, "his_context_enabled", False, raising=False)


def _create_visit(client, headers) -> dict:
    patients = client.get("/api/v1/patients", headers=headers).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patients[0]["id"], "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    return created.json()["data"]


def test_flag_off_by_default_context_unavailable(client, doctor_token, owner_engine):
    """العلم مطفأ افتراضياً — الزيارة تمضي وcontext_unavailable=true."""
    headers = auth(doctor_token)
    visit = _create_visit(client, headers)
    with owner_engine.connect() as conn:
        snapshot_id = conn.execute(text(
            "SELECT context_snapshot_id FROM visits WHERE id = :v"), {"v": visit["id"]}).scalar_one()
    assert snapshot_id is not None
    context = visit["context_snapshot"]
    assert context.get("context_unavailable") is True
    assert (context.get("his") or {}).get("reason") == "disabled"


def test_context_available_reaches_snapshot_and_review_panel(client, doctor_token, admin_token,
                                                             fhir_server, his_enabled):
    """سياق متاح → يدخل اللقطة ولوحة المراجعة (والحساسيات بارزة)."""
    admin_headers = auth(admin_token)
    assert client.patch("/api/v1/settings/integration", headers=admin_headers,
                        json={"endpoint_url": fhir_server}).status_code == 200
    try:
        headers = auth(doctor_token)
        visit = _create_visit(client, headers)
        context = visit["context_snapshot"]
        assert context["context_unavailable"] is False
        assert context["his"]["available"] is True
        assert CONDITION_TEXT in context["problems"]
        assert MEDICATION_TEXT in context["medications"]
        assert context["allergies"] == [ALLERGY_TEXT]

        # اللوحة في شاشة المراجعة — بعد اكتمال الدورة إلى in_review
        from tests.conftest import record_consent

        visit_id = visit["id"]
        record_consent(client, visit_id, headers)
        client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
        client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                    json={"duration_sec": 25})
        summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
        panel = summary["patient_context"]
        assert panel is not None
        assert panel["his_available"] is True and panel["context_unavailable"] is False
        assert panel["allergies"] == [ALLERGY_TEXT]
        assert CONDITION_TEXT in panel["problems"]
    finally:
        client.patch("/api/v1/settings/integration", headers=admin_headers,
                     json={"endpoint_url": ""})


def test_his_down_does_not_block_and_logs_no_phi(client, doctor_token, admin_token,
                                                 his_enabled, caplog):
    """HIS ساقط → الزيارة تُنشأ، العلم مضبوط، ولا PHI في السجل."""
    admin_headers = auth(admin_token)
    # منفذ مغلق — الاتصال يفشل فوراً
    assert client.patch("/api/v1/settings/integration", headers=admin_headers,
                        json={"endpoint_url": "http://127.0.0.1:9"}).status_code == 200
    try:
        headers = auth(doctor_token)
        with caplog.at_level(logging.WARNING, logger="medify.his_context"):
            visit = _create_visit(client, headers)
        assert visit["id"], "الزيارة أُنشئت رغم سقوط HIS"
        context = visit["context_snapshot"]
        assert context["context_unavailable"] is True
        assert context["his"]["reason"] in ("error", "timeout")

        messages = " ".join(record.getMessage() for record in caplog.records)
        assert messages, "العطل سُجّل"
        for forbidden in ("1042376", "9900", "@", "Penicillin"):
            assert forbidden not in messages, "لا PHI ولا معرّفات مرضى في السجل"
    finally:
        client.patch("/api/v1/settings/integration", headers=admin_headers,
                     json={"endpoint_url": ""})


def test_merge_context_keeps_sources_distinct():
    from app.services.his_context import merge_context

    medify = {"problems": ["Hypertension (I10)"], "medications": ["Amlodipine"], "allergies": []}
    his = {"available": True, "problems": ["Type 2 diabetes"], "medications": ["Amlodipine", "Metformin"],
           "allergies": ["Penicillin"], "demographics": {"gender": "male"}}
    merged = merge_context(medify, his)
    assert merged["context_unavailable"] is False
    assert merged["problems"] == ["Hypertension (I10)", "Type 2 diabetes"]
    assert merged["medications"] == ["Amlodipine", "Metformin"], "لا تكرار"
    assert merged["allergies"] == ["Penicillin"]
    assert merged["his"]["available"] is True

    unavailable = merge_context(medify, {"available": False, "reason": "timeout"})
    assert unavailable["context_unavailable"] is True
    assert unavailable["his"]["reason"] == "timeout"
