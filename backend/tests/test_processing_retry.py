"""المرحلة 3 — إعادة المحاولة التلقائية لخطوط المعالجة + سجل processing_attempts.

معايير القبول: timeout مرتين ثم نجاح → لا MDF-5031 | فشول متتالية حتى الاستنفاد →
MDF-5031 بسجل كامل + إخطار | ملف تالف → فوري بمحاولة واحدة (non_retryable).
فشل P3 يبقى غير معطِّل (ملخص بلا إرشادات + MDF-5033).

الوضع inline (conftest: PROCESSING_MODE=inline, PROCESSING_RETRY_DELAYS=0,0,0) —
منطق المحاولات يُختبر بذاته بلا أزمنة جدار.
"""
from __future__ import annotations

import wave

import pytest
from sqlalchemy import text

from tests.conftest import auth, record_consent


def _recording_visit(client, headers, patient_id: str) -> str:
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    return visit_id


def _attempts(owner_engine, visit_id: str, stage: str) -> list:
    with owner_engine.connect() as conn:
        return conn.execute(text(
            "SELECT attempt_no, error_class, succeeded FROM processing_attempts "
            "WHERE visit_id = :id AND stage = :stage ORDER BY attempt_no"
        ), {"id": visit_id, "stage": stage}).fetchall()


def _failure_notifications(owner_engine, visit_id: str) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(text(
            "SELECT count(*) FROM notifications WHERE kind = 'dr.analysis_failed' "
            "AND payload_json->>'visit_id' = :id"
        ), {"id": visit_id}).scalar_one()


class _FlakySTT:
    """محرك يفشل N مرات بخطأ محدد ثم يعيد تفريغاً صالحاً."""

    def __init__(self, failures: int, exc_factory):
        self.failures = failures
        self.exc_factory = exc_factory
        self.calls = 0

    def transcribe_visit(self, path: str) -> list[dict]:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc_factory()
        return [
            {"id": "s-0", "text": "مرحباً دكتور عندي صداع", "t0": 0.0, "t1": 3.0, "speaker": "patient"},
            {"id": "s-1", "text": "من متى بدأ الصداع؟", "t0": 3.0, "t1": 5.0, "speaker": "doctor"},
        ]


@pytest.fixture(scope="module")
def retry_patient(client, doctor_token) -> str:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900803", "display_name": "مريض إعادة المحاولة"})
    assert created.status_code == 201, created.text
    return created.json()["data"]["id"]


def test_transient_timeouts_then_success_no_mdf5031(client, doctor_token, retry_patient,
                                                    owner_engine, monkeypatch):
    """timeout مرتين ثم نجاح: التدفق يكتمل، السجل ثلاث محاولات، لا إخطار فشل."""
    headers = auth(doctor_token)
    visit_id = _recording_visit(client, headers, retry_patient)
    engine = _FlakySTT(2, lambda: TimeoutError("request timed out"))
    monkeypatch.setattr("app.pipelines.run.get_stt", lambda: engine)

    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 20})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["data"]["state"] == "in_review"
    assert engine.calls == 3

    rows = _attempts(owner_engine, visit_id, "P1")
    assert [(r.attempt_no, r.error_class, r.succeeded) for r in rows] == [
        (1, "retryable", False), (2, "retryable", False), (3, "none", True),
    ]
    assert _failure_notifications(owner_engine, visit_id) == 0


def test_exhausted_retries_mdf5031_with_full_log_and_notification(client, doctor_token, retry_patient,
                                                                  owner_engine, monkeypatch):
    """فشل عابر مستمر: 4 محاولات (أولى + 3 إعادات) ثم MDF-5031 + إخطار — والسجل ينجو من rollback."""
    headers = auth(doctor_token)
    visit_id = _recording_visit(client, headers, retry_patient)
    engine = _FlakySTT(99, lambda: ConnectionError("connection reset by peer"))
    monkeypatch.setattr("app.pipelines.run.get_stt", lambda: engine)

    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 20})
    assert stopped.status_code == 500
    assert stopped.json()["error"]["code"] == "MDF-5031"
    assert engine.calls == 4

    rows = _attempts(owner_engine, visit_id, "P1")
    assert len(rows) == 4
    assert all(r.error_class == "retryable" and not r.succeeded for r in rows)
    assert _failure_notifications(owner_engine, visit_id) == 1

    # rollback الطلب أعاد الزيارة إلى recording — الدكتور يعيد الإنهاء بعد زوال العطل
    recording_now = client.get("/api/v1/visits", headers=headers,
                               params={"state": "recording", "per_page": 100}).json()["data"]
    assert visit_id in {row["id"] for row in recording_now}


def test_corrupt_file_fails_fast_single_attempt(client, doctor_token, retry_patient,
                                                owner_engine, monkeypatch):
    """ملف تالف = non_retryable: محاولة واحدة ثم MDF-5031 فوراً — لا عبث إعادات."""
    headers = auth(doctor_token)
    visit_id = _recording_visit(client, headers, retry_patient)
    engine = _FlakySTT(99, lambda: wave.Error("file does not start with RIFF id"))
    monkeypatch.setattr("app.pipelines.run.get_stt", lambda: engine)

    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 20})
    assert stopped.status_code == 500
    assert stopped.json()["error"]["code"] == "MDF-5031"
    assert engine.calls == 1

    rows = _attempts(owner_engine, visit_id, "P1")
    assert [(r.attempt_no, r.error_class, r.succeeded) for r in rows] == [(1, "non_retryable", False)]
    assert _failure_notifications(owner_engine, visit_id) == 1


def test_p3_failure_retried_then_nonblocking(client, doctor_token, retry_patient,
                                             owner_engine, monkeypatch):
    """فشل P3 بعد استنفاد إعاداته لا يحجب: in_review بملخص بلا إرشادات + MDF-5033."""
    headers = auth(doctor_token)
    visit_id = _recording_visit(client, headers, retry_patient)

    from app.pipelines import run as run_module
    real_llm = run_module.get_llm()

    class _P3FailingLLM:
        def complete_json(self, prompt_id, version, variables, attachments=None):
            if prompt_id == "P3-guidance":
                raise ConnectionError("connection refused")
            return real_llm.complete_json(prompt_id, version, variables, attachments=attachments)

    monkeypatch.setattr("app.pipelines.run.get_llm", lambda: _P3FailingLLM())

    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 20})
    assert stopped.status_code == 200, stopped.text
    data = stopped.json()["data"]
    assert data["state"] == "in_review"
    assert data["guidance_ok"] is False

    rows = _attempts(owner_engine, visit_id, "P3")
    assert len(rows) == 4 and all(not r.succeeded for r in rows)
    assert _failure_notifications(owner_engine, visit_id) == 1  # MDF-5033

    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    assert summary["sections"], "الملخص متاح بلا إرشادات"
    assert all(not section["guidance"] for section in summary["sections"])
