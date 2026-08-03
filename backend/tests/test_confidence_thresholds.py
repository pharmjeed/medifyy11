"""المرحلة 11 — إبراز الثقة المنخفضة: التقاط إشارات Whisper، تشاؤم الجملة، عتبات حية.

معايير القبول: segment مشوّش → جملته مبرزة ونقرتها تشغّل مصدرها | تسجيل نظيف →
لا إبراز | تغيير العتبة يسري بلا deploy.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import auth, record_consent


class _FakeWhisperSegment:
    def __init__(self, text: str, start: float, end: float, avg_logprob: float, no_speech_prob: float):
        self.text = text
        self.start = start
        self.end = end
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob


def test_whisper_confidence_normalized_0_1():
    """إشارتا Whisper تُطبَّعان: exp(avg_logprob) مخصوماً منه احتمال «لا كلام»."""
    from app.pipelines.stt import WhisperSTTEngine

    clean = _FakeWhisperSegment("واضح", 0.0, 2.0, avg_logprob=-0.05, no_speech_prob=0.01)
    noisy = _FakeWhisperSegment("مشوّش", 2.0, 4.0, avg_logprob=-1.6, no_speech_prob=0.35)
    silentish = _FakeWhisperSegment("همس", 4.0, 6.0, avg_logprob=-0.2, no_speech_prob=0.9)

    clean_score = WhisperSTTEngine._segment_confidence(clean)
    noisy_score = WhisperSTTEngine._segment_confidence(noisy)
    silent_score = WhisperSTTEngine._segment_confidence(silentish)

    for score in (clean_score, noisy_score, silent_score):
        assert score is not None and 0.0 <= score <= 1.0
    assert clean_score > 0.9, "مقطع نظيف يقارب 1"
    assert noisy_score < 0.55, "مقطع مشوّش دون العتبة الدنيا الافتراضية"
    assert silent_score < noisy_score or silent_score < 0.3, "احتمال «لا كلام» العالي يخفض الدرجة"
    # مقطع بلا إشارات (محرك لا يوفرها) → None بلا انفجار
    assert WhisperSTTEngine._segment_confidence(object()) is None


def test_sentence_confidence_is_minimum_of_its_segments():
    """تشاؤم مقصود: ثقة الجملة = أدنى مقاطعها لا متوسطها."""
    from app.services.evidence import build_section_evidence

    segments = {
        "s-0": {"id": "s-0", "t0": 0.0, "t1": 2.0, "confidence": 0.92},
        "s-1": {"id": "s-1", "t0": 2.0, "t1": 4.0, "confidence": 0.41},
        "s-2": {"id": "s-2", "t0": 4.0, "t1": 6.0, "confidence": 0.88},
    }
    entries = build_section_evidence(
        [
            {"text": "جملة من مقطعين.", "segment_ids": ["s-0", "s-1"]},
            {"text": "جملة نظيفة.", "segment_ids": ["s-2"]},
            {"text": "بلا سند.", "segment_ids": []},
        ],
        segments,
    )
    assert entries[0]["confidence"] == 0.41, "الأدنى لا المتوسط"
    assert entries[0]["audio_start_ms"] == 0 and entries[0]["audio_end_ms"] == 4000
    assert entries[1]["confidence"] == 0.88
    assert entries[2]["confidence"] is None and entries[2]["segment_ids"] == []


def test_clean_recording_has_no_highlighting_and_thresholds_are_live(client, doctor_token, owner_engine):
    """تسجيل نظيف (mock=0.9) → لا جملة دون العتبة؛ ورفع العتبة من الكونسول يبرزها فوراً."""
    from app.services.stt_confidence import SETTING_KEY

    headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=headers).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patients[0]["id"], "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                       json={"duration_sec": 40}).status_code == 200

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    stt = summary["stt_confidence"]
    assert stt["thresholds"] == {"low": 0.55, "medium": 0.75}, "الافتراضات"
    assert stt["mean"] == 0.9 and stt["min"] == 0.9
    sentences = [s for section in summary["sections"] for s in (section["evidence"] or [])]
    scored = [s for s in sentences if s["confidence"] is not None]
    assert scored, "الجمل المسنودة تحمل درجة"
    assert all(s["confidence"] >= stt["thresholds"]["medium"] for s in scored), "لا إبراز لتسجيل نظيف"

    # رفع العتبة من كونسول المالك — يسري فوراً بلا deploy
    with owner_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO platform_settings (id, key, value, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :k, CAST(:v AS jsonb), now(), now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ), {"k": SETTING_KEY, "v": '{"low": 0.6, "medium": 0.95}'})
    try:
        summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
        assert summary["stt_confidence"]["thresholds"] == {"low": 0.6, "medium": 0.95}
        scored = [s for section in summary["sections"] for s in (section["evidence"] or [])
                  if s["confidence"] is not None]
        assert all(s["confidence"] < 0.95 for s in scored), "العتبة الجديدة تبرزها الآن"
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("DELETE FROM platform_settings WHERE key = :k"), {"k": SETTING_KEY})


def test_confidence_scores_reach_telemetry_as_numbers(client, doctor_token, caplog):
    """الدرجات تدخل telemetry أرقاماً (لا محتوى) — analytics يرفض أي مفتاح محظور."""
    import json
    import logging

    headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=headers).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patients[0]["id"], "template_id": templates[0]["id"]})
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)
    with caplog.at_level(logging.INFO, logger="medify.analytics"):
        client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                    json={"duration_sec": 30})
    events = [json.loads(record.getMessage()) for record in caplog.records
              if record.name == "medify.analytics"]
    generated = next(e for e in events if e["event"] == "summary.generated")
    assert isinstance(generated["confidence_mean"], (int, float))
    assert isinstance(generated["confidence_min"], (int, float))
