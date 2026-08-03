"""المرحلة 10 — السند المرتبط: جملة ↔ مقاطع صوت/تفريغ بأزمنة ms + وسوم المصدر.

معايير القبول: نقرة جملة → المقطع الصحيح ±1ث (الأزمنة تُخزَّن بدقة من P1) |
جملة بلا سند → الوسم يظهر | تعديل يدوي → الوسم يتحول «تحرير طبيب».

يستخدم مرضى seed حصراً — الملف يسبق اختبار العزل أبجدياً.
"""
from __future__ import annotations

import wave
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.conftest import auth, record_consent


@pytest.fixture(scope="module")
def journey(client, doctor_token):
    headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=headers).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patients[0]["id"], "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 48})
    assert stopped.status_code == 200, stopped.text
    return {"visit_id": visit_id, "headers": headers}


def test_evidence_generated_with_segment_mapping_and_ms(client, journey):
    headers = journey["headers"]
    visit_id = journey["visit_id"]

    transcript = client.get(f"/api/v1/visits/{visit_id}/transcript", headers=headers).json()["data"]
    segments = {s["id"]: s for s in transcript["content"]["segments"]}
    assert segments

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    first = summary["sections"][0]
    assert first["evidence"], "السند مخزَّن مع القسم"

    mapped = [e for e in first["evidence"] if e["segment_ids"]]
    assert mapped, "جمل مسنودة موجودة"
    entry = mapped[0]
    assert entry["origin"] == "ai"
    assert entry["text"] in first["content_current"]
    starts = [segments[sid]["t0"] for sid in entry["segment_ids"]]
    ends = [segments[sid]["t1"] for sid in entry["segment_ids"]]
    # الدقة المطلوبة ±1ث تتحقق من المصدر نفسه: التخزين بالمللي ثانية من أزمنة P1 حرفياً
    assert entry["audio_start_ms"] == int(min(starts) * 1000)
    assert entry["audio_end_ms"] == int(max(ends) * 1000)

    # جملة بلا سند (عدّاد mock يتجاوز مقاطع الحوار) → الوسم متاح للواجهة
    all_entries = [e for s in summary["sections"] for e in (s["evidence"] or [])]
    assert any(not e["segment_ids"] for e in all_entries), "«بلا مصدر صوتي» حالة قائمة"

    # نقطة السند المستقلة (م10)
    evidence = client.get(f"/api/v1/visits/{visit_id}/evidence", headers=headers).json()["data"]
    assert evidence["visit_id"] == visit_id
    assert evidence["sections"][0]["sentences"] == first["evidence"]


def test_manual_edit_marks_doctor_origin(client, journey):
    headers = journey["headers"]
    visit_id = journey["visit_id"]
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    section = summary["sections"][0]
    kept_first = (section["evidence"] or [])[0]

    edited = client.patch(f"/api/v1/summary-sections/{section['id']}",
                          headers={**headers, "If-Match": summary["etag"]},
                          json={"content_current": section["content_current"] + " Doctor added note sentence."})
    assert edited.status_code == 200, edited.text

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    evidence = summary["sections"][0]["evidence"]
    assert evidence[0]["text"] == kept_first["text"]
    assert evidence[0]["origin"] == "ai", "الجمل غير المعدَّلة تحتفظ بسندها"
    assert evidence[0]["segment_ids"] == kept_first["segment_ids"]
    last = evidence[-1]
    assert last["text"] == "Doctor added note sentence."
    assert last["origin"] == "doctor", "الوسم تحوّل إلى «تحرير طبيب»"
    assert last["segment_ids"] == [] and last["audio_start_ms"] is None


def test_audio_endpoint_supports_range_and_scoped_auth(client, doctor_token, foreign_doctor_token,
                                                       owner_engine, journey):
    visit_id = journey["visit_id"]
    with owner_engine.connect() as conn:
        storage_uri = conn.execute(text(
            "SELECT storage_uri FROM recordings WHERE visit_id = :v"), {"v": visit_id}).scalar_one()
    path = Path(storage_uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x01\x02" * 4000)
    size = path.stat().st_size

    partial = client.get(f"/api/v1/visits/{visit_id}/audio",
                         params={"token": doctor_token}, headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206
    assert len(partial.content) == 100
    assert partial.headers["Content-Range"] == f"bytes 0-99/{size}"
    assert partial.headers["Accept-Ranges"] == "bytes"

    full = client.get(f"/api/v1/visits/{visit_id}/audio", params={"token": doctor_token})
    assert full.status_code == 200 and len(full.content) == size

    tail = client.get(f"/api/v1/visits/{visit_id}/audio",
                      params={"token": doctor_token}, headers={"Range": f"bytes={size - 10}-"})
    assert tail.status_code == 206 and len(tail.content) == 10

    foreign = client.get(f"/api/v1/visits/{visit_id}/audio", params={"token": foreign_doctor_token})
    assert foreign.status_code == 404, "لا كشف عن وجود المورد خارج النطاق"

    anonymous = client.get(f"/api/v1/visits/{visit_id}/audio", params={"token": "bogus"})
    assert anonymous.status_code == 401
