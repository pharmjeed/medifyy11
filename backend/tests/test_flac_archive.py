"""المرحلة 9 — أرشفة FLAC: دورة كاملة بمطابقة فك التشفير، وفشل مفتعل يبقي WAV.

تتخطى تلقائياً إن غاب ffmpeg عن بيئة التشغيل.
"""
from __future__ import annotations

import hashlib
import uuid
import wave
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import auth, record_consent


ffmpeg_missing = False
try:
    from app.services.audio_archive import ffmpeg_available

    ffmpeg_missing = not ffmpeg_available()
except Exception:  # pragma: no cover
    ffmpeg_missing = True

pytestmark = pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg غير متوفر")


def _recording_visit_with_wav(client, headers, owner_engine) -> tuple[str, Path, bytes]:
    patients = client.get("/api/v1/patients", headers=headers).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patients[0]["id"], "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    with owner_engine.connect() as conn:
        storage_uri = conn.execute(text(
            "SELECT storage_uri FROM recordings WHERE visit_id = :v"), {"v": visit_id}).scalar_one()
    wav_path = Path(storage_uri)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    # نغمة PCM16 حقيقية — ليست صمتاً كي تكون المطابقة ذات معنى
    frames = bytes(
        b for i in range(16000) for b in int(8000 * ((i % 200) - 100) / 100).to_bytes(2, "little", signed=True)
    )
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(frames)
    return visit_id, wav_path, frames


def test_full_archive_cycle_decoded_hash_matches(client, doctor_token, owner_engine):
    from app.models import Visit
    from app.services.audio_archive import _decoded_pcm_hash, archive_recording_to_flac

    headers = auth(doctor_token)
    visit_id, wav_path, frames = _recording_visit_with_wav(client, headers, owner_engine)
    original_hash = hashlib.sha256(frames).hexdigest()

    with Session(owner_engine) as db:
        visit = db.get(Visit, uuid.UUID(visit_id))
        assert archive_recording_to_flac(db, visit) is True
        db.commit()

    flac_path = wav_path.with_suffix(".flac")
    assert flac_path.exists(), "ناتج FLAC موجود"
    assert not wav_path.exists(), "الأصل حُذف بعد نجاح المطابقة حصراً"
    # تحقق مستقل عن تحقق الخدمة: فكّ الأرشيف يطابق العينات الأصلية حرفياً
    assert _decoded_pcm_hash(flac_path) == original_hash

    with owner_engine.connect() as conn:
        storage_uri = conn.execute(text(
            "SELECT storage_uri FROM recordings WHERE visit_id = :v"), {"v": visit_id}).scalar_one()
        assert storage_uri.endswith(".flac"), "مرجع التخزين تحدّث"
        audited = conn.execute(text(
            "SELECT count(*) FROM audit_logs WHERE action = 'recording.archived_flac' "
            "AND entity_id IN (SELECT id::text FROM recordings WHERE visit_id = :v)"), {"v": visit_id}
        ).scalar_one()
        assert audited == 1


def test_verify_mismatch_keeps_wav_and_alerts(client, doctor_token, owner_engine, monkeypatch):
    from app.models import Visit
    from app.services.audio_archive import archive_recording_to_flac

    headers = auth(doctor_token)
    visit_id, wav_path, _frames = _recording_visit_with_wav(client, headers, owner_engine)

    # فشل مطابقة مفتعل: الفك «يعيد» بصمة خاطئة
    monkeypatch.setattr("app.services.audio_archive._decoded_pcm_hash", lambda _path: "0" * 64)

    with Session(owner_engine) as db:
        visit = db.get(Visit, uuid.UUID(visit_id))
        assert archive_recording_to_flac(db, visit) is False
        db.commit()

    assert wav_path.exists(), "الأصل لا يُمس عند فشل المطابقة"
    assert not wav_path.with_suffix(".flac").exists(), "الناتج الفاسد أُتلف"
    with owner_engine.connect() as conn:
        storage_uri = conn.execute(text(
            "SELECT storage_uri FROM recordings WHERE visit_id = :v"), {"v": visit_id}).scalar_one()
        assert storage_uri.endswith(".wav"), "المرجع لم يتغيّر"
        alerted = conn.execute(text(
            "SELECT count(*) FROM audit_logs WHERE action = 'recording.flac_verify_failed' "
            "AND entity_id IN (SELECT id::text FROM recordings WHERE visit_id = :v)"), {"v": visit_id}
        ).scalar_one()
        assert alerted == 1, "الإنذار مدوَّن"
