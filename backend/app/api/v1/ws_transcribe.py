"""WSS /ws/visits/{id}/transcribe — بروتوكول DOC-05 §٥ (P1: partial ≤ 2s، final بطوابع، resume_from)."""
from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ...config import get_settings
from ...db import rls_session
from ...models import Recording, Transcript, Visit
from ...pipelines.speaker import attribute_speaker
from ...pipelines.stt import STTSegment, get_stt, pcm_to_wav
from ...security import decode_token

router = APIRouter()
logger = logging.getLogger("medify.ws")


class _AudioSink:
    """يكتب PCM الوارد إلى ملف الزيارة أولاً بأول ثم يصحّح أطوال WAV عند الإغلاق.

    الكتابة إلحاقية لسببين: إعادة الاتصال وسط الاستشارة (NFR-09) يجب ألا تمحو ما سُجّل
    قبلها، والتسجيل الحقيقي لا يُحتجز في الذاكرة (استشارة 30 دقيقة ≈ 57MB لكل جلسة).
    """

    HEADER_BYTES = 44  # ترويسة WAV القياسية التي تكتبها وحدة wave (RIFF+fmt+data)

    def __init__(self, storage_uri: str, sample_rate: int) -> None:
        self._path = Path(storage_uri)
        self._sample_rate = sample_rate
        self._is_wav = self._path.suffix.lower() == ".wav"
        self._handle = None

    def write(self, pcm: bytes) -> None:
        if not pcm:
            return
        if self._handle is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._is_wav and (not self._path.exists() or self._path.stat().st_size < self.HEADER_BYTES):
                self._path.write_bytes(pcm_to_wav(b"", self._sample_rate))  # ترويسة بأطوال صفرية تُصحَّح لاحقاً
            self._handle = self._path.open("ab")
        self._handle.write(pcm)

    def close(self) -> float:
        """يُغلق الملف ويعيد المدة الكلية بالثواني — شاملةً ما كتبته اتصالات سابقة لنفس الزيارة."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if not self._path.exists():
            return 0.0
        size = self._path.stat().st_size
        data_bytes = max(0, size - self.HEADER_BYTES) if self._is_wav else size
        if self._is_wav and data_bytes > 0:
            with self._path.open("r+b") as handle:  # تصحيح طولي RIFF وdata بعد الإلحاق
                handle.seek(4)
                handle.write((36 + data_bytes).to_bytes(4, "little"))
                handle.seek(40)
                handle.write(data_bytes.to_bytes(4, "little"))
        return data_bytes / 2 / self._sample_rate


@router.websocket("/ws/visits/{visit_id}/transcribe")
async def transcribe_ws(websocket: WebSocket, visit_id: uuid.UUID, token: str = ""):
    """يعمل فقط والزيارة في حالة recording — المصادقة عبر ?token= (WSS خلف Caddy في الإنتاج)."""
    try:
        payload = decode_token(token, "access")
    except Exception:
        await websocket.close(code=4401)
        return
    if payload.get("role") != "doctor":
        await websocket.close(code=4403)
        return
    facility_id = payload["facility_id"]
    doctor_id = payload["sub"]

    with rls_session(facility_id, doctor_id, "doctor") as db:
        visit = db.execute(select(Visit).where(Visit.id == visit_id)).scalar_one_or_none()
        if visit is None or visit.state != "recording":
            await websocket.close(code=4409)
            return
        recording_row = db.execute(select(Recording).where(Recording.visit_id == visit_id)).scalar_one_or_none()
        recording_uri = recording_row.storage_uri if recording_row is not None else None
        # إعادة اتصال وسط الاستشارة: نُكمل فوق التفريغ السابق ولا نستبدله (وإلا ضاع نصفها الأول)
        prior = db.execute(select(Transcript).where(Transcript.visit_id == visit_id)).scalar_one_or_none()
        segments: list[dict] = list((prior.content_json or {}).get("segments", [])) if prior is not None else []

    await websocket.accept()
    stt = get_stt()
    settings = get_settings()
    session_id = f"{visit_id}"
    last_seq = -1
    paused = False
    sink = _AudioSink(recording_uri, settings.audio_sample_rate) if recording_uri is not None else None

    async def emit(produced: list[STTSegment], seq: int) -> None:
        """يبثّ ما أنتجه المحرك ويحفظ المقاطع النهائية بإسناد المتحدث."""
        for segment in produced:
            if segment.is_final:
                segment_id = f"s-{len(segments)}"
                # إسناد المتحدث بالمحتوى + سياق الدور السابق (طبيب/مريض)
                prev_speaker = segments[-1]["speaker"] if segments else None
                speaker, speaker_confidence = attribute_speaker(segment.text, prev_speaker)
                segments.append({
                    "id": segment_id, "text": segment.text, "t0": segment.t0, "t1": segment.t1,
                    "speaker": speaker, "speaker_confidence": speaker_confidence,
                })
                await websocket.send_json({
                    "type": "final", "segment_id": segment_id,
                    "text": segment.text, "t0": segment.t0, "t1": segment.t1,
                    "speaker": speaker, "speaker_confidence": speaker_confidence,
                })
            else:
                await websocket.send_json({"type": "partial", "seq": seq, "text": segment.text})

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            if msg_type == "audio_chunk":
                seq = int(message.get("seq", 0))
                if seq <= last_seq:
                    continue  # جزء مكرر بعد إعادة اتصال
                if seq > last_seq + 1:
                    # فجوة — اطلب الإعادة من آخر جزء مؤكد (NFR-09)
                    await websocket.send_json({"type": "resume_from", "seq": last_seq + 1})
                    continue
                last_seq = seq
                if paused:
                    continue
                chunk_payload = message.get("payload", "")
                if sink is not None:
                    try:
                        sink.write(base64.b64decode(chunk_payload))
                    except Exception as exc:
                        logger.warning("audio write failed for visit %s: %s", visit_id, exc)
                try:
                    # المحركات الحقيقية تستدعي الشبكة — تُنفَّذ في خيط كي لا تُجمّد حلقة الأحداث
                    produced = await asyncio.to_thread(
                        lambda: list(stt.stream_chunk(session_id, seq, chunk_payload))
                    )
                    await emit(produced, seq)
                except Exception as exc:  # انقطاع خط P1
                    logger.error("P1 error: %s", exc)
                    await websocket.send_json({"type": "error", "code": "MDF-5031"})

            elif msg_type == "pause":
                paused = True
                await websocket.send_json({"type": "status", "state": "paused"})
            elif msg_type == "resume":
                paused = False
                await websocket.send_json({"type": "status", "state": "recording"})
            elif msg_type == "resume_query":
                await websocket.send_json({"type": "resume_from", "seq": last_seq + 1})
            elif msg_type == "end":
                # آخر نافذة صوت لم تكتمل — تُفرَّغ قبل الإغلاق كي لا تضيع خاتمة الاستشارة
                try:
                    tail = await asyncio.to_thread(lambda: list(stt.finish(session_id)))
                    await emit(tail, last_seq)
                except Exception as exc:
                    logger.error("P1 tail error: %s", exc)
                await websocket.send_json({"type": "status", "state": "summarizing"})
                break
    except WebSocketDisconnect:
        logger.info("WS disconnected for visit %s at seq %s", visit_id, last_seq)
    except Exception as exc:
        # قناة مقطوعة أثناء إرسال أو خطأ غير متوقع — التفريغ المتجمّع يُحفظ رغم ذلك
        logger.warning("WS terminated for visit %s: %s", visit_id, exc)

    recorded_seconds = sink.close() if sink is not None else 0.0

    # حفظ التفريغ والصوت — يبقى مرتبطاً بالزيارة (FR-604)
    with rls_session(facility_id, doctor_id, "doctor") as db:
        visit = db.execute(select(Visit).where(Visit.id == visit_id)).scalar_one_or_none()
        if visit is None:
            return
        if segments:
            transcript = db.execute(select(Transcript).where(Transcript.visit_id == visit.id)).scalar_one_or_none()
            if transcript is None:
                db.add(Transcript(
                    visit_id=visit.id,
                    facility_id=visit.facility_id,
                    content_json={"segments": segments},
                    language_stats={"segments": len(segments)},
                ))
            else:
                transcript.content_json = {"segments": segments}
        recording = db.execute(select(Recording).where(Recording.visit_id == visit.id)).scalar_one_or_none()
        if recording is not None and recorded_seconds > 0:
            # الملف كُتب أولاً بأول أثناء البث (WAV يُشفَّر تخزيناً بتشفير القرص في الإنتاج)
            recording.duration_sec = max(recording.duration_sec, int(recorded_seconds))
    try:
        await websocket.close()
    except Exception:
        pass
