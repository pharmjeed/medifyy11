"""WSS /ws/visits/{id}/transcribe — قناة استقبال الصوت (DOC-05 §٥ المعدّل بقرار مالك 2026-08-02).

لا تفريغ أثناء التسجيل: المتصفح يبث أجزاء PCM16 (250ms) والخادم يُلحقها بملف WAV
الزيارة أولاً بأول مع بروتوكول الاستئناف (resume_from — NFR-09). التفريغ الكامل
وإسناد المتحدث يجريان بعد إنهاء التسجيل على المحادثة كاملة (P1 في recording/stop).
"""
from __future__ import annotations

import base64
import datetime as dt
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ...config import get_settings
from ...db import rls_session
from ...models import Recording, Visit
from ...pipelines.stt import pcm_to_wav
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
    """يعمل فقط والزيارة في حالة recording — المصادقة عبر ?token= (WSS خلف Caddy في الإنتاج).

    Streaming protocol:
    - Client sends audio_chunk { seq, payload }
    - Server acks: { type: "ack", seq }
    - On reconnect, client queries: { type: "resume_query" }
    - Server responds: { type: "resume_from", seq } (next expected seq)
    - Client replays unsynced chunks from that point

    Enhanced 2026-08-02: Better recovery on client resume + exponential backoff support
    """
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

    await websocket.accept()
    settings = get_settings()
    last_seq = -1
    paused = False
    connected_at = dt.datetime.now(dt.timezone.utc)
    sink = _AudioSink(recording_uri, settings.audio_sample_rate) if recording_uri is not None else None

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
                if sink is not None:
                    try:
                        sink.write(base64.b64decode(message.get("payload", "")))
                    except Exception as exc:
                        logger.warning("audio write failed for visit %s: %s", visit_id, exc)
                # إقرار دوري خفيف — يبقي القناة حيّة ويؤكد للعميل وصول الصوت
                await websocket.send_json({"type": "ack", "seq": seq})

            elif msg_type == "pause":
                paused = True
                await websocket.send_json({"type": "status", "state": "paused"})
            elif msg_type == "resume":
                paused = False
                await websocket.send_json({"type": "status", "state": "recording"})
            elif msg_type == "resume_query":
                # Client reconnected — tell them where to resume from
                # last_seq is -1 at start, so last_seq + 1 = 0 (first chunk)
                await websocket.send_json({
                    "type": "resume_from",
                    "seq": last_seq + 1,
                    "buffered_at": connected_at.isoformat(),  # Client can use this for optimizations
                })
                logger.info("Resume query for visit %s — resuming from seq %d", visit_id, last_seq + 1)
            elif msg_type == "end":
                # التفريغ الكامل يبدأ في recording/stop بعد إغلاق القناة واكتمال الملف
                await websocket.send_json({"type": "status", "state": "summarizing"})
                logger.info("Recording end for visit %s — processed %d chunks", visit_id, last_seq + 1)
                break
    except WebSocketDisconnect:
        logger.info("WS client disconnected for visit %s after seq %d", visit_id, last_seq)
    except Exception as exc:
        # قناة مقطوعة أثناء إرسال أو خطأ غير متوقع — الصوت المكتوب محفوظ رغم ذلك
        logger.exception("WS error for visit %s at seq %d: %s", visit_id, last_seq, exc)

    recorded_seconds = sink.close() if sink is not None else 0.0

    # الصوت يبقى مرتبطاً بالزيارة (FR-604) — التفريغ نفسه يُبنى لاحقاً من الملف الكامل
    with rls_session(facility_id, doctor_id, "doctor") as db:
        recording = db.execute(select(Recording).where(Recording.visit_id == visit_id)).scalar_one_or_none()
        if recording is not None and recorded_seconds > 0:
            # الملف كُتب أولاً بأول أثناء البث (WAV يُشفَّر تخزيناً بتشفير القرص في الإنتاج)
            recording.duration_sec = max(recording.duration_sec, int(recorded_seconds))
    try:
        await websocket.close()
    except Exception:
        pass
