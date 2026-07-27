"""محرك التفريغ الحي بجيميناي — منطق النوافذ والصمت والطوابع الزمنية (بلا أي نداء شبكة).

العميل يُستبدل بمزيّف، بينما تُبنى كائنات google.genai.types الحقيقية — فيتحقق شكل الاستدعاء أيضاً.
"""
from __future__ import annotations

import base64
import io
import math
import wave
from types import SimpleNamespace

import pytest

from app.pipelines.stt import GeminiSTTEngine, MockSTTEngine, pcm_rms, pcm_to_wav

RATE = 16000
WINDOW_SECONDS = 4.0
CHUNK_SECONDS = 0.25


def tone_pcm(seconds: float, amplitude: int = 9000) -> bytes:
    """نغمة 440Hz كبديل عن كلام — ما يهم هو تجاوزها عتبة الصمت."""
    frames = int(seconds * RATE)
    return b"".join(
        int(amplitude * math.sin(2 * math.pi * 440 * index / RATE)).to_bytes(2, "little", signed=True)
        for index in range(frames)
    )


def silence_pcm(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * RATE)


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.reply = "المريض يشكو من صداع منذ خمسة أيام"

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(text=self.reply)


def make_engine() -> GeminiSTTEngine:
    """نسخة بلا __init__ — لا مفتاح ولا عميل حقيقي."""
    engine = GeminiSTTEngine.__new__(GeminiSTTEngine)
    engine._client = SimpleNamespace(models=_FakeModels())
    engine._model = "gemini-test"
    engine._sample_rate = RATE
    engine._silence_threshold = 200
    engine._window_bytes = int(WINDOW_SECONDS * RATE * 2)
    engine._sessions = {}
    return engine


def feed(engine: GeminiSTTEngine, pcm: bytes, session: str = "v1") -> list:
    """يمرر الصوت بأجزاء 250ms كما ترسلها الواجهة."""
    step = int(CHUNK_SECONDS * RATE * 2)
    produced = []
    for index in range(0, len(pcm), step):
        payload = base64.b64encode(pcm[index:index + step]).decode()
        produced.extend(engine.stream_chunk(session, index // step, payload))
    return produced


def test_wav_wrapper_is_readable_pcm16_mono():
    data = pcm_to_wav(tone_pcm(0.5), RATE)
    with wave.open(io.BytesIO(data), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == RATE
        assert handle.getnframes() == int(0.5 * RATE)


def test_rms_separates_speech_from_silence():
    assert pcm_rms(silence_pcm(1.0)) == 0.0
    assert pcm_rms(tone_pcm(1.0)) > 200
    assert pcm_rms(b"") == 0.0


def test_no_call_before_window_is_full():
    engine = make_engine()
    produced = feed(engine, tone_pcm(WINDOW_SECONDS - CHUNK_SECONDS))
    assert produced == []
    assert engine._client.models.calls == [], "لا استدعاء قبل اكتمال النافذة"


def test_full_window_yields_one_final_segment_with_timestamps():
    engine = make_engine()
    produced = feed(engine, tone_pcm(WINDOW_SECONDS * 2))
    assert len(produced) == 2
    first, second = produced
    assert first.is_final and second.is_final, "لا partial من نموذج غير متدفق"
    assert first.t0 == 0.0 and first.t1 == pytest.approx(WINDOW_SECONDS, abs=0.05)
    assert second.t0 == pytest.approx(WINDOW_SECONDS, abs=0.05), "الطوابع متصلة بين النوافذ"
    assert len(engine._client.models.calls) == 2
    # النافذة الثانية تحمل ذيل الأولى سياقاً
    prompt_parts = engine._client.models.calls[1]["contents"][0].parts
    assert any("سياق" in (part.text or "") for part in prompt_parts if part.text)


def test_silence_window_costs_nothing_but_keeps_the_clock():
    engine = make_engine()
    assert feed(engine, silence_pcm(WINDOW_SECONDS)) == []
    assert engine._client.models.calls == [], "الصمت لا يُرسل للنموذج"
    produced = feed(engine, tone_pcm(WINDOW_SECONDS))
    assert len(produced) == 1
    assert produced[0].t0 == pytest.approx(WINDOW_SECONDS, abs=0.05), "ساعة الجلسة تقدمت رغم تخطي الصمت"


def test_finish_flushes_the_unfinished_tail_once():
    engine = make_engine()
    assert feed(engine, tone_pcm(2.0)) == []
    tail = list(engine.finish("v1"))
    assert len(tail) == 1 and tail[0].t1 == pytest.approx(2.0, abs=0.05)
    assert list(engine.finish("v1")) == [], "الجلسة تُنظَّف بعد الإنهاء"


def test_tail_shorter_than_threshold_is_dropped():
    engine = make_engine()
    feed(engine, tone_pcm(0.5))
    assert list(engine.finish("v1")) == []
    assert engine._client.models.calls == []


def test_empty_model_reply_produces_no_segment():
    engine = make_engine()
    engine._client.models.reply = "   "
    assert feed(engine, tone_pcm(WINDOW_SECONDS)) == []


def test_transcribe_file_missing_path_is_silent():
    assert make_engine().transcribe_file("var/does-not-exist.wav") == ""


def test_mock_engine_has_no_session_tail():
    """finish() الافتراضية لا تُنتج شيئاً — المحرك التجريبي يبثّ بالتسلسل فقط."""
    assert list(MockSTTEngine().finish("v1")) == []


# ===== محرك التلخيص/الإرشاد بجيميناي (LLM_ENGINE=gemini) =====

def make_llm_engine():
    from app.pipelines.llm import GeminiEngine

    engine = GeminiEngine.__new__(GeminiEngine)
    engine._client = SimpleNamespace(models=_FakeModels())
    engine._model = "gemini-test"
    return engine


def test_gemini_llm_returns_parsed_json_and_model_ref():
    engine = make_llm_engine()
    engine._client.models.reply = '{"sections": [{"section_key": "S", "content": "شكوى صداع"}]}'
    output, model_ref = engine.complete_json(
        "P2-summary", "1.0",
        {"template_structure": {"sections": []}, "transcript": "نص", "patient_context": {}},
    )
    assert output["sections"][0]["section_key"] == "S"
    assert model_ref == "P2-summary@1.0/gemini-test"
    assert engine._client.models.calls[0]["config"].response_mime_type == "application/json"


def test_gemini_llm_retries_once_on_invalid_json_then_raises():
    engine = make_llm_engine()
    engine._client.models.reply = "ليس JSON"
    with pytest.raises(ValueError):
        engine.complete_json("P2-summary", "1.0", {"transcript": "نص"})
    assert len(engine._client.models.calls) == 2, "إعادة واحدة ثم رفع الخطأ (DOC-08 §٦)"


def test_gemini_llm_passes_attachments_as_inline_bytes():
    engine = make_llm_engine()
    engine._client.models.reply = '{"name": "قالب", "sections": []}'
    engine.complete_json(
        "P4-reverse-template", "1.0", {"sample_text": "نموذج"},
        attachments=[{"media_type": "image/png", "data": base64.b64encode(b"PNGDATA").decode()}],
    )
    parts = engine._client.models.calls[0]["contents"][0].parts
    assert parts[0].inline_data.data == b"PNGDATA"
    assert parts[0].inline_data.mime_type == "image/png"
