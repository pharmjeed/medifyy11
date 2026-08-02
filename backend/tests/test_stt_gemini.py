"""محرك التفريغ بجيميناي — تفريغ الملف الكامل بعد الإنهاء مع تمييز المتحدث (بلا أي نداء شبكة).

قرار مالك 2026-08-02: لا تفريغ أثناء التسجيل — المحادثة تُفرَّغ كاملة تمريرة واحدة.
العميل يُستبدل بمزيّف، بينما تُبنى كائنات google.genai.types الحقيقية — فيتحقق شكل الاستدعاء أيضاً.
"""
from __future__ import annotations

import base64
import io
import math
import wave
from types import SimpleNamespace

import pytest

from app.pipelines.stt import MOCK_DIALOGUE, GeminiSTTEngine, MockSTTEngine, pcm_to_wav

RATE = 16000


def tone_pcm(seconds: float, amplitude: int = 9000) -> bytes:
    """نغمة 440Hz كبديل عن كلام — المهم محتوى صوتي غير فارغ."""
    frames = int(seconds * RATE)
    return b"".join(
        int(amplitude * math.sin(2 * math.pi * 440 * index / RATE)).to_bytes(2, "little", signed=True)
        for index in range(frames)
    )


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.reply = (
            '{"segments": ['
            '{"speaker": "patient", "text": "السلام عليكم دكتور عندي صداع", "t0": 0.0, "t1": 3.4, "confidence": 0.97},'
            '{"speaker": "doctor", "text": "خليني أقيس لك الضغط", "t0": 3.4, "t1": 6.1, "confidence": 0.93}'
            "]}"
        )

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(text=self.reply)


def make_engine() -> GeminiSTTEngine:
    """نسخة بلا __init__ — لا مفتاح ولا عميل حقيقي."""
    engine = GeminiSTTEngine.__new__(GeminiSTTEngine)
    engine._client = SimpleNamespace(models=_FakeModels())
    engine._model = "gemini-test"
    return engine


@pytest.fixture()
def visit_wav(tmp_path):
    path = tmp_path / "visit.wav"
    path.write_bytes(pcm_to_wav(tone_pcm(1.0), RATE))
    return str(path)


def test_wav_wrapper_is_readable_pcm16_mono():
    data = pcm_to_wav(tone_pcm(0.5), RATE)
    with wave.open(io.BytesIO(data), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == RATE
        assert handle.getnframes() == int(0.5 * RATE)


def test_transcribe_visit_parses_diarized_segments(visit_wav):
    engine = make_engine()
    segments = engine.transcribe_visit(visit_wav)
    assert len(segments) == 2
    first, second = segments
    assert first["id"] == "s-0" and second["id"] == "s-1"
    assert first["speaker"] == "patient" and second["speaker"] == "doctor"
    assert first["speaker_confidence"] == 0.97
    assert first["t0"] == 0.0 and first["t1"] == pytest.approx(3.4)
    assert second["t0"] == pytest.approx(3.4)
    assert len(engine._client.models.calls) == 1, "الملف الكامل تمريرة واحدة — لا نوافذ"
    # الصوت يُرسل بايتات مضمّنة + مطالبة التمييز
    parts = engine._client.models.calls[0]["contents"][0].parts
    assert parts[0].inline_data.mime_type == "audio/wav"
    assert any("doctor" in (part.text or "") for part in parts if part.text)


def test_transcribe_visit_missing_file_returns_empty():
    engine = make_engine()
    assert engine.transcribe_visit("var/does-not-exist.wav") == []
    assert engine._client.models.calls == [], "ملف غائب = لا استدعاء ولا اختلاق"


def test_transcribe_visit_skips_empty_text_and_foreign_speaker(visit_wav):
    engine = make_engine()
    engine._client.models.reply = (
        '{"segments": ['
        '{"speaker": "doctor", "text": "  ", "t0": 0, "t1": 1},'
        '{"speaker": "nurse", "text": "كلام بمتحدث غير قانوني", "t0": 1, "t1": 2},'
        '{"speaker": "patient", "text": "أحس بدوخة", "confidence": 1.7}'
        "]}"
    )
    segments = engine.transcribe_visit(visit_wav)
    assert len(segments) == 2
    assert "speaker" not in segments[0], "متحدث خارج العقد يسقط — يُسند لغوياً في P1"
    assert segments[1]["speaker"] == "patient"
    assert segments[1]["speaker_confidence"] == 0.99, "الثقة تُقصّ على [0, 0.99]"
    assert segments[1]["t0"] == pytest.approx(2.0), "زمن غائب يُكمل من ساعة آخر مقطع"


def test_transcribe_visit_retries_once_on_invalid_json_then_raises(visit_wav):
    engine = make_engine()
    engine._client.models.reply = "ليس JSON"
    with pytest.raises(RuntimeError):
        engine.transcribe_visit(visit_wav)
    assert len(engine._client.models.calls) == 2, "إعادة واحدة ثم رفع الخطأ (نمط DOC-08 §٦)"


def test_transcribe_visit_empty_recording_yields_no_segments(visit_wav):
    engine = make_engine()
    engine._client.models.reply = '{"segments": []}'
    assert engine.transcribe_visit(visit_wav) == []


def test_transcribe_file_missing_path_is_silent():
    assert make_engine().transcribe_file("var/does-not-exist.wav") == ""


def test_mock_engine_returns_full_dialogue_with_timestamps():
    segments = MockSTTEngine().transcribe_visit("ignored.wav")
    assert [segment["text"] for segment in segments] == MOCK_DIALOGUE
    assert segments[0]["t0"] == 0.0
    assert all(segments[i]["t0"] < segments[i + 1]["t0"] for i in range(len(segments) - 1))
    assert all("speaker" not in segment for segment in segments), "الإسناد اللغوي في P1 لا في المحرك"


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
