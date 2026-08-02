"""المرحلة 6 — دورة النسخ: reopen → v+1 → بوابتان → نقل بدلالة replace.

معايير القبول: v1 سليمة حرفياً بعد نقل v2 | v2 تحمل amended + relatesTo/replaces
للوثيقة السابقة حصراً | reopen من غير uploaded → 409 | UPDATE على نسخة منقولة →
استثناء قاعدة | retry-upload لا ينشئ نسخة ولا بوابات.
"""
from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.conftest import auth, record_consent


def _visit_uploaded(client, headers, patient_id: str) -> str:
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


def _bundle_file(visit_id: str, version: int) -> dict:
    base = Path(os.environ["RECORDINGS_DIR"]).parent / "fhir"
    suffix = f".v{version}" if version > 1 else ""
    path = base / f"{visit_id}{suffix}.json"
    assert path.exists(), f"حزمة النسخة {version} غير مخزّنة"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ver_patient(client, doctor_token) -> str:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900805", "display_name": "مريض دورة النسخ"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def test_full_reopen_cycle_v1_intact_v2_replaces(client, doctor_token, ver_patient):
    headers = auth(doctor_token)
    visit_id = _visit_uploaded(client, headers, ver_patient)

    # v1: الحزمة صالحة R4 (request لكل مدخل) + final + DocumentReference بلا relatesTo
    bundle_v1 = _bundle_file(visit_id, 1)
    assert all("request" in entry and entry["request"].get("method") == "POST"
               for entry in bundle_v1["entry"]), "transaction يتطلب request لكل مدخل"
    composition_v1 = next(e["resource"] for e in bundle_v1["entry"]
                          if e["resource"]["resourceType"] == "Composition")
    assert composition_v1["status"] == "final"
    docref_v1 = next(e["resource"] for e in bundle_v1["entry"]
                     if e["resource"]["resourceType"] == "DocumentReference")
    assert "relatesTo" not in docref_v1

    v1_export = client.get(f"/api/v1/visits/{visit_id}/export/text", headers=headers,
                           params={"version": 1}).json()["data"]["content"]
    assert f"النسخة 1" in v1_export

    # reopen — نسخة 2 والحالة تعود للمراجعة والتحرير يعود متاحاً
    reopened = client.post(f"/api/v1/visits/{visit_id}/reopen", headers=headers,
                           json={"reason": "وصلت نتيجة مختبر تغيّر الخطة"})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["data"] == {"state": "in_review", "version": 2}

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    assert summary["version"] == 2
    assert summary["note_approved"] is False, "بوابتا النسخة الجديدة مستقلتان"
    assert summary["can_export"] is True, "آخر منقولة تبقى قابلة للتصدير أثناء الإعداد"
    by_number = {row["version_number"]: row for row in summary["versions"]}
    assert by_number[1]["upload_status"] == "uploaded"
    assert by_number[2]["upload_status"] == "draft"
    assert by_number[2]["reopen_reason"] == "وصلت نتيجة مختبر تغيّر الخطة"

    # التحرير عاد (التجميد كان لدورة v1) — إضافة الجملة الجديدة
    section = summary["sections"][0]
    edited = client.patch(f"/api/v1/summary-sections/{section['id']}",
                          headers={**headers, "If-Match": summary["etag"]},
                          json={"content_current": section["content_current"] + " نتيجة المختبر: التهاب بكتيري."})
    assert edited.status_code == 200, edited.text

    # البوابتان من جديد ثم نقل v2
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["upload"]["status"] == "confirmed"

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    by_number = {row["version_number"]: row for row in summary["versions"]}
    assert by_number[2]["upload_status"] == "uploaded"
    assert by_number[2]["diff_counts"]["sections_changed"] >= 1

    # v1 سليمة حرفياً — التصدير قبل النقل الثاني وبعده متطابق
    v1_after = client.get(f"/api/v1/visits/{visit_id}/export/text", headers=headers,
                          params={"version": 1}).json()["data"]["content"]
    assert v1_after == v1_export, "لقطة v1 لا تتأثر بنقل v2"

    # v2: amended + relatesTo/replaces يستهدف وثيقة Medify v1 حصراً
    bundle_v2 = _bundle_file(visit_id, 2)
    composition_v2 = next(e["resource"] for e in bundle_v2["entry"]
                          if e["resource"]["resourceType"] == "Composition")
    assert composition_v2["status"] == "amended"
    docref_v2 = next(e["resource"] for e in bundle_v2["entry"]
                     if e["resource"]["resourceType"] == "DocumentReference")
    relates = docref_v2["relatesTo"]
    assert len(relates) == 1 and relates[0]["code"] == "replaces"
    assert relates[0]["target"]["identifier"]["value"] == f"urn:medify:doc:{visit_id}:1"

    # التصدير الافتراضي الآن = v2 (آخر منقولة) وبتذييل النسخة
    default_export = client.get(f"/api/v1/visits/{visit_id}/export/text", headers=headers).json()["data"]
    assert default_export["version"] == 2
    assert "نتيجة المختبر" in default_export["content"]
    assert "النسخة 2" in default_export["content"]


def test_reopen_requires_uploaded_state_and_reason(client, doctor_token, ver_patient):
    headers = auth(doctor_token)
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": ver_patient, "template_id": templates[0]["id"]})
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers, json={"duration_sec": 20})

    blocked = client.post(f"/api/v1/visits/{visit_id}/reopen", headers=headers,
                          json={"reason": "قبل النقل"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "MDF-4223"

    # سبب من مسافات فقط مرفوض
    uploaded_id = _visit_uploaded(client, headers, ver_patient)
    blank = client.post(f"/api/v1/visits/{uploaded_id}/reopen", headers=headers,
                        json={"reason": "   "})
    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "MDF-4225"


def test_uploaded_version_immutable_at_db_level(client, doctor_token, ver_patient, owner_engine):
    """المبدأ 3: النسخة المنقولة لا UPDATE عليها أبداً — حتى لمالك القاعدة."""
    headers = auth(doctor_token)
    visit_id = _visit_uploaded(client, headers, ver_patient)
    with owner_engine.connect() as conn:
        with pytest.raises(Exception, match="immutable"):
            conn.execute(text(
                "UPDATE note_versions SET upload_status = 'pending' WHERE visit_id = :id"
            ), {"id": visit_id})
    with owner_engine.connect() as conn:
        with pytest.raises(Exception, match="append-only"):
            conn.execute(text("DELETE FROM note_versions WHERE visit_id = :id"), {"id": visit_id})


def test_retry_upload_same_version_no_new_gates(client, doctor_token, admin_token, ver_patient, owner_engine):
    """الفصل الصارم: retry-upload = نفس النسخة بلا بوابات؛ لا صف نسخة جديداً ولا اعتماداً."""
    headers = auth(doctor_token)
    admin_headers = auth(admin_token)
    # وجهة فاشلة (المحرك الوهمي يفشل على fail-unreachable)
    assert client.patch("/api/v1/settings/integration", headers=admin_headers,
                        json={"endpoint_url": "https://his.example/fail-unreachable"}).status_code == 200
    try:
        templates = client.get("/api/v1/templates", headers=headers).json()["data"]
        created = client.post("/api/v1/visits", headers=headers,
                              json={"patient_id": ver_patient, "template_id": templates[0]["id"]})
        visit_id = created.json()["data"]["id"]
        record_consent(client, visit_id, headers)
        client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
        client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers, json={"duration_sec": 20})
        summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
        for section in summary["sections"]:
            for item in section["guidance"]:
                if item["status"] == "pending":
                    client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                                 json={"status": "rejected"})
        assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
        approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
        assert approved.status_code == 200
        assert approved.json()["data"]["upload"]["status"] == "failed"

        def _counts() -> tuple[int, int, int]:
            with owner_engine.connect() as conn:
                return (
                    conn.execute(text("SELECT count(*) FROM note_versions WHERE visit_id = :id"),
                                 {"id": visit_id}).scalar_one(),
                    conn.execute(text("SELECT count(*) FROM approvals WHERE visit_id = :id"),
                                 {"id": visit_id}).scalar_one(),
                    conn.execute(text("SELECT count(*) FROM note_approvals WHERE visit_id = :id"),
                                 {"id": visit_id}).scalar_one(),
                )

        summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
        assert summary["state"] == "upload_failed"
        assert summary["versions"][0]["upload_status"] == "upload_failed"
        before = _counts()

        # إصلاح الوجهة (فارغة = نجاح وهمي) ثم retry — بلا أي بوابة جديدة
        assert client.patch("/api/v1/settings/integration", headers=admin_headers,
                            json={"endpoint_url": ""}).status_code == 200
        retried = client.post(f"/api/v1/visits/{visit_id}/upload-retry", headers=headers)
        assert retried.status_code == 200, retried.text
        assert retried.json()["data"]["status"] == "confirmed"

        summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
        assert summary["state"] == "uploaded"
        assert summary["versions"][0]["upload_status"] == "uploaded"
        assert _counts() == before, "retry-upload لا ينشئ نسخة ولا اعتمادات"
    finally:
        client.patch("/api/v1/settings/integration", headers=admin_headers,
                     json={"endpoint_url": ""})


def test_hl7_mdm_builder_and_mllp_roundtrip():
    """محوّل MDM: T02 لأول نسخة، T09 للاستبدال بمرجع الأم — وMLLP يقرأ ACK صحيحاً."""
    from app.services.hl7 import build_mdm, send_mllp

    first = build_mdm(
        control_id="visit-1:1", event="T02", patient_mrn="1042376",
        patient_name="مريض تجريبي", doctor_name="د. نورة",
        doc_identifier="urn:medify:doc:visit-1:1", parent_doc_identifier=None,
        note_text="S: صداع\nP: مسكن",
    )
    assert "MDM^T02" in first and "visit-1:1" in first
    assert "urn:medify:doc:visit-1:1" in first
    replacement = build_mdm(
        control_id="visit-1:2", event="T09", patient_mrn="1042376",
        patient_name="مريض تجريبي", doctor_name="د. نورة",
        doc_identifier="urn:medify:doc:visit-1:2",
        parent_doc_identifier="urn:medify:doc:visit-1:1",
        note_text="S: صداع\nP: مسكن + مضاد",
    )
    txa = next(seg for seg in replacement.split("\r") if seg.startswith("TXA"))
    fields = txa.split("|")
    assert fields[12] == "urn:medify:doc:visit-1:2"  # TXA-12 وثيقة النسخة
    assert fields[13] == "urn:medify:doc:visit-1:1"  # TXA-13 الأم — الاستبدال يستهدفها حصراً

    # خادم MLLP خيطي يرد ACK AA
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def _serve() -> None:
        conn, _addr = server.accept()
        with conn:
            data = b""
            while b"\x1c" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            ack = "MSH|^~\\&|HIS|HIS|MEDIFY|MEDIFY|20260803||ACK|1|P|2.5\rMSA|AA|1\r"
            conn.sendall(b"\x0b" + ack.encode() + b"\x1c\x0d")

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    delivered, code = send_mllp("127.0.0.1", port, replacement, timeout=10)
    thread.join(timeout=10)
    server.close()
    assert delivered is True and code == "AA"
