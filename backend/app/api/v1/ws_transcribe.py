"""WSS /ws/visits/{id}/transcribe — بروتوكول DOC-05 §٥ (P1: partial ≤ 2s، final بطوابع، resume_from)."""
from __future__ import annotations

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
from ...pipelines.stt import get_stt
from ...security import decode_token

router = APIRouter()
logger = logging.getLogger("medify.ws")


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

    await websocket.accept()
    stt = get_stt()
    session_id = f"{visit_id}"
    last_seq = -1
    paused = False
    segments: list[dict] = []
    audio_buffer = bytearray()

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
                try:
                    audio_buffer.extend(base64.b64decode(chunk_payload))
                except Exception:
                    pass
                try:
                    for segment in stt.stream_chunk(session_id, seq, chunk_payload):
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
                await websocket.send_json({"type": "status", "state": "summarizing"})
                break
    except WebSocketDisconnect:
        logger.info("WS disconnected for visit %s at seq %s", visit_id, last_seq)

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
        if recording is not None and audio_buffer:
            path = Path(recording.storage_uri)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes(audio_buffer))  # يُشفَّر تخزيناً عبر تشفير القرص/المجلد في الإنتاج
            recording.duration_sec = max(recording.duration_sec, int((last_seq + 1) * 0.25))
    try:
        await websocket.close()
    except Exception:
        pass
