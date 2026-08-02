"""المرحلة 2 — سجل مقاطع الصوت الخادمي: ترقيم معمَّر عبر الاتصالات + idempotency
+ تحقق finalize الصارم (MDF-4234).

معايير القبول: قتل التبويبة منتصف التسجيل → استئناف بلا فقد | مقطع مكرر لا يتكرر
بالتجميع | الملف المجمّع bit-exact مقابل مرجع | فجوة في السجل → 409 بقائمة الناقص.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.conftest import auth, record_consent

PCM = b"\x01\x02" * 2000  # 4000 بايت = 0.125 ثانية PCM16 عند 16kHz
PAYLOAD = base64.b64encode(PCM).decode()
DIGEST = hashlib.sha256(PCM).hexdigest()


def _recording_visit(client, headers, patient_id: str) -> str:
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    return visit_id


def _wav_data_bytes(visit_id: str) -> bytes:
    path = Path(os.environ["RECORDINGS_DIR"]) / f"{visit_id}.wav"
    assert path.exists()
    return path.read_bytes()[44:]


def _ledger_count(owner_engine, visit_id: str) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(text(
            "SELECT count(*) FROM audio_chunks WHERE visit_id = :id"
        ), {"id": visit_id}).scalar_one()


@pytest.fixture(scope="module")
def chunk_patient(client, doctor_token) -> str:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900802", "display_name": "مريض سجل المقاطع"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def test_resume_position_survives_tab_kill_no_loss(client, doctor_token, chunk_patient):
    """قتل التبويبة (اتصال يسقط بلا end): الاتصال الجديد يستأنف من سجل الخادم — صفر فقد."""
    headers = auth(doctor_token)
    visit_id = _recording_visit(client, headers, chunk_patient)

    with client.websocket_connect(f"/ws/visits/{visit_id}/transcribe?token={doctor_token}") as ws:
        for seq in range(5):
            ws.send_json({"type": "audio_chunk", "seq": seq, "payload": PAYLOAD, "sha256": DIGEST})
            assert ws.receive_json() == {"type": "ack", "seq": seq}
    # سقوط بلا end — كما عند قتل التبويبة

    with client.websocket_connect(f"/ws/visits/{visit_id}/transcribe?token={doctor_token}") as ws:
        ws.send_json({"type": "resume_query"})
        resumed = ws.receive_json()
        assert resumed["type"] == "resume_from"
        assert resumed["seq"] == 5, "الموضع من السجل المعمَّر — لا يعود للصفر بعد قتل التبويبة"
        for seq in range(5, 10):
            ws.send_json({"type": "audio_chunk", "seq": seq, "payload": PAYLOAD, "sha256": DIGEST})
            assert ws.receive_json() == {"type": "ack", "seq": seq}
        ws.send_json({"type": "end"})
        assert ws.receive_json() == {"type": "status", "state": "summarizing"}

    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 2})
    assert stopped.status_code == 200, stopped.text
    # bit-exact: الملف المجمّع يطابق المرجع (10 مقاطع متتالية) حرفياً
    assert _wav_data_bytes(visit_id) == PCM * 10


def test_duplicate_chunk_reacked_without_double_append(client, doctor_token, chunk_patient, owner_engine):
    """ضياع ack: العميل يعيد الإرسال — الخادم يعيد الإقرار بلا كتابة (idempotent)."""
    headers = auth(doctor_token)
    visit_id = _recording_visit(client, headers, chunk_patient)

    with client.websocket_connect(f"/ws/visits/{visit_id}/transcribe?token={doctor_token}") as ws:
        for seq in range(3):
            ws.send_json({"type": "audio_chunk", "seq": seq, "payload": PAYLOAD, "sha256": DIGEST})
            assert ws.receive_json() == {"type": "ack", "seq": seq}
        # إعادة إرسال مقطع مُقرّ (سيناريو ack ضائع) — re-ack يحرر مخزن العميل، بلا إلحاق ثانٍ
        ws.send_json({"type": "audio_chunk", "seq": 1, "payload": PAYLOAD, "sha256": DIGEST})
        assert ws.receive_json() == {"type": "ack", "seq": 1}
        ws.send_json({"type": "end"})
        ws.receive_json()

    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 1})
    assert stopped.status_code == 200, stopped.text
    assert _wav_data_bytes(visit_id) == PCM * 3, "المكرر لا يدخل التجميع"
    assert _ledger_count(owner_engine, visit_id) == 3


def test_checksum_mismatch_rejected_then_clean_retry(client, doctor_token, chunk_patient, owner_engine):
    """بصمة لا تطابق البايتات = تلف في الطريق — لا كتابة، والإعادة السليمة تمر."""
    headers = auth(doctor_token)
    visit_id = _recording_visit(client, headers, chunk_patient)

    with client.websocket_connect(f"/ws/visits/{visit_id}/transcribe?token={doctor_token}") as ws:
        ws.send_json({"type": "audio_chunk", "seq": 0, "payload": PAYLOAD, "sha256": "0" * 64})
        rejected = ws.receive_json()
        assert rejected["type"] == "chunk_error"
        assert rejected["seq"] == 0 and rejected["reason"] == "checksum_mismatch"
        ws.send_json({"type": "audio_chunk", "seq": 0, "payload": PAYLOAD, "sha256": DIGEST})
        assert ws.receive_json() == {"type": "ack", "seq": 0}
        ws.send_json({"type": "end"})
        ws.receive_json()

    assert _ledger_count(owner_engine, visit_id) == 1
    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 1})
    assert stopped.status_code == 200, stopped.text
    assert _wav_data_bytes(visit_id) == PCM


def test_sequence_gap_requests_resume_from_last_confirmed(client, doctor_token, chunk_patient):
    headers = auth(doctor_token)
    visit_id = _recording_visit(client, headers, chunk_patient)
    with client.websocket_connect(f"/ws/visits/{visit_id}/transcribe?token={doctor_token}") as ws:
        for seq in range(2):
            ws.send_json({"type": "audio_chunk", "seq": seq, "payload": PAYLOAD, "sha256": DIGEST})
            ws.receive_json()
        ws.send_json({"type": "audio_chunk", "seq": 7, "payload": PAYLOAD, "sha256": DIGEST})
        resume = ws.receive_json()
        assert resume["type"] == "resume_from" and resume["seq"] == 2


def test_finalize_gap_returns_409_with_missing_list(client, doctor_token, chunk_patient, owner_engine):
    """فجوة في السجل عند الإنهاء → MDF-4234 بقائمة الناقص والزيارة تبقى recording."""
    headers = auth(doctor_token)
    visit_id = _recording_visit(client, headers, chunk_patient)

    with client.websocket_connect(f"/ws/visits/{visit_id}/transcribe?token={doctor_token}") as ws:
        for seq in range(4):
            ws.send_json({"type": "audio_chunk", "seq": seq, "payload": PAYLOAD, "sha256": DIGEST})
            ws.receive_json()
        ws.send_json({"type": "end"})
        ws.receive_json()

    # فقد مفتعل لأول مقطع (فساد سجل) — finalize يجب أن يكشفه لا أن يمرّره لP1
    with owner_engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM audio_chunks WHERE visit_id = :id AND chunk_index = 0"
        ), {"id": visit_id})

    blocked = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 1})
    assert blocked.status_code == 409, blocked.text
    body = blocked.json()["error"]
    assert body["code"] == "MDF-4234"
    assert body["details"]["missing_chunks"] == [0]

    state = client.get("/api/v1/visits", headers=headers,
                       params={"state": "recording", "per_page": 100}).json()["data"]
    assert visit_id in {row["id"] for row in state}, "الزيارة باقية recording لإعادة المزامنة"
