"""محرك STT قابل للتبديل — STT_ENGINE=gemini|whisper|mock (P1 — DOC-08 §١).

mock: مولّد نص عربي سريري تجريبي متدفق — لا يوقف أي شيء عند غياب الموارد (D-04).
gemini: تفريغ حي بنوافذ صوتية عبر Gemini متعدد الوسائط (تعديل مالك 2026-07-26).
whisper: faster-whisper (small, CPU int8) داخل الحاوية.
"""
from __future__ import annotations

import array
import base64
import io
import logging
import wave
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field

from ..config import get_settings

logger = logging.getLogger("medify.pipelines")


@dataclass
class STTSegment:
    text: str
    t0: float
    t1: float
    is_final: bool


class STTEngine(ABC):
    @abstractmethod
    def stream_chunk(self, session_id: str, seq: int, payload_b64: str) -> Iterator[STTSegment]:
        """يعالج جزء صوت 250ms ويُنتج partial/final."""

    @abstractmethod
    def transcribe_file(self, path: str) -> str:
        """مسار قصير غير متدفق — إملاء التحرير الصوتي (FR-706)."""

    def finish(self, session_id: str) -> Iterator[STTSegment]:
        """ما تبقّى في مخزن الجلسة عند إنهاء التسجيل — افتراضياً لا شيء."""
        return iter(())


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """يغلّف PCM16 أحادي بترويسة WAV — الصيغة التي تقبلها نماذج الصوت وتُخزَّن بها التسجيلات."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def pcm_rms(pcm: bytes) -> float:
    """جذر متوسط المربعات لعينات PCM16 — بوابة الصمت قبل أي استدعاء مدفوع."""
    if len(pcm) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return 0.0
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


# نص عربي سريري تجريبي (يحاكي محادثة عيادة — عربي بلهجاته + مقاطع إنجليزية مختلطة)
MOCK_DIALOGUE: list[str] = [
    "السلام عليكم دكتور، والله من خمس أيام وأنا أحس بصداع قدّامي مزعج.",
    "الصداع يزيد الصبح وأحياناً معه دوخة خفيفة.",
    "بصراحة يا دكتور الشهر الأخير ما كنت منتظم على حبوب الضغط.",
    "طيب، خليني أقيس لك الضغط الحين.",
    "القياس اليوم مرتفع — مية وخمسة وستين على خمسة وتسعين.",
    "النبض اثنين وثمانين، منتظم، والحرارة طبيعية.",
    "الفحص العصبي سليم ولا يوجد ما يقلق في فحص القلب.",
    "التقييم المبدئي: ارتفاع ضغط غير منضبط بسبب عدم الانتظام على العلاج، والصداع على الأغلب مرتبط به — tension-type headache.",
    "نرجع نبدأ amlodipine خمسة مليجرام مرة واحدة يومياً.",
    "وأبيك تقيس الضغط في البيت مرتين يومياً وتسجل القراءات أسبوعين.",
    "نشوفك بعد أسبوعين بالمواعيد، وإذا صار صداع شديد أو تغير في النظر تراجع الطوارئ فوراً.",
    "وضحت للمريض أهمية الالتزام بالعلاج وتقليل الملح في الأكل.",
]


class MockSTTEngine(STTEngine):
    """كل 4 أجزاء (~ثانية صوت) يُبث سطر جديد من الحوار — partial ثم final بطوابع زمنية."""

    CHUNKS_PER_SENTENCE = 4
    CHUNK_SECONDS = 0.25

    def stream_chunk(self, session_id: str, seq: int, payload_b64: str) -> Iterator[STTSegment]:
        sentence_index = seq // self.CHUNKS_PER_SENTENCE
        position = seq % self.CHUNKS_PER_SENTENCE
        if sentence_index >= len(MOCK_DIALOGUE):
            return
        sentence = MOCK_DIALOGUE[sentence_index]
        t0 = sentence_index * self.CHUNKS_PER_SENTENCE * self.CHUNK_SECONDS
        if position < self.CHUNKS_PER_SENTENCE - 1:
            words = sentence.split()
            cut = max(1, int(len(words) * (position + 1) / self.CHUNKS_PER_SENTENCE))
            yield STTSegment(text=" ".join(words[:cut]), t0=t0, t1=t0 + (position + 1) * self.CHUNK_SECONDS, is_final=False)
        else:
            yield STTSegment(text=sentence, t0=t0, t1=t0 + self.CHUNKS_PER_SENTENCE * self.CHUNK_SECONDS, is_final=True)

    def transcribe_file(self, path: str) -> str:
        return "Patient advised to continue current plan and return if symptoms worsen."


GEMINI_TRANSCRIBE_PROMPT = (
    "أنت محرك تفريغ صوتي طبي داخل عيادة سعودية. فرّغ الكلام في المقطع الصوتي حرفياً كما نُطق.\n"
    "- العربية بلهجاتها تُكتب عربية، والمصطلحات والأدوية الإنجليزية تُكتب لاتينية كما نُطقت.\n"
    "- لا تترجم، ولا تلخّص، ولا تصحّح، ولا تضف أي تعليق أو وصف للأصوات أو ترقيماً للمتحدثين.\n"
    "- إن لم يكن في المقطع كلام مسموع فأعد نصاً فارغاً تماماً.\n"
    "أعد نص التفريغ فقط بلا أي مقدمة."
)

_AUDIO_MIME_BY_SUFFIX = {
    ".wav": "audio/wav", ".mp3": "audio/mp3", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac", ".aiff": "audio/aiff",
}


@dataclass
class _GeminiSession:
    """مخزن جلسة زيارة واحدة: صوت لم يُفرَّغ بعد + ساعة التسجيل + ذيل النص كسياق للنافذة التالية."""

    buffer: bytearray = field(default_factory=bytearray)
    elapsed: float = 0.0
    tail: str = ""


class GeminiSTTEngine(STTEngine):
    """تفريغ حي بنوافذ صوتية — كل ~4 ثوانٍ صوت تُرسل كـWAV إلى Gemini ويعود مقطع final.

    لا partial: النموذج غير متدفق، والنافذة القصيرة تبقي زمن الظهور قريباً من NFR-01.
    نوافذ الصمت تُتخطى قبل الاستدعاء (بوابة RMS) فلا كلفة ولا نص مُختلَق من سكوت.
    """

    def __init__(self) -> None:
        from google import genai  # استيراد كسول — الحزمة اختيارية على بيئات الـmock

        settings = get_settings()
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_stt_model or settings.gemini_model
        self._sample_rate = settings.audio_sample_rate
        self._silence_threshold = settings.stt_silence_threshold
        self._window_bytes = max(1, int(settings.stt_window_seconds * self._sample_rate * 2))
        self._sessions: dict[str, _GeminiSession] = {}

    # ----- البث الحي -----

    def stream_chunk(self, session_id: str, seq: int, payload_b64: str) -> Iterator[STTSegment]:
        session = self._sessions.setdefault(session_id, _GeminiSession())
        try:
            session.buffer.extend(base64.b64decode(payload_b64))
        except Exception:
            logger.warning("جزء صوت غير صالح (seq=%s) — تُخطّي", seq)
            return
        if len(session.buffer) < self._window_bytes:
            return
        yield from self._drain(session)

    def finish(self, session_id: str) -> Iterator[STTSegment]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        yield from self._drain(session, minimum_seconds=0.8)

    def _drain(self, session: _GeminiSession, minimum_seconds: float = 0.0) -> Iterator[STTSegment]:
        pcm = bytes(session.buffer)
        session.buffer.clear()
        duration = len(pcm) / 2 / self._sample_rate
        if duration <= minimum_seconds:
            session.elapsed += duration
            return
        t0 = session.elapsed
        session.elapsed += duration
        if pcm_rms(pcm) < self._silence_threshold:
            return  # صمت — لا استدعاء
        text = self._transcribe_pcm(pcm, session.tail)
        if not text:
            return
        session.tail = text[-400:]
        yield STTSegment(text=text, t0=round(t0, 2), t1=round(session.elapsed, 2), is_final=True)

    # ----- الاستدعاء -----

    def _generate(self, parts: list, prompt: str) -> str:
        from google.genai import types

        content = types.Content(role="user", parts=[*parts, types.Part.from_text(text=prompt)])
        last_error: Exception | None = None
        for attempt in range(2):  # فشل عابر → إعادة واحدة قبل رفع MDF-5031 من طبقة الـWS
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=[content],
                    config=types.GenerateContentConfig(temperature=0.0),
                )
                return (response.text or "").strip()
            except Exception as exc:
                last_error = exc
                logger.warning("Gemini STT — فشل المحاولة %s: %s", attempt + 1, exc)
        raise RuntimeError(f"Gemini STT failed: {last_error}")

    def _transcribe_pcm(self, pcm: bytes, context: str) -> str:
        from google.genai import types

        prompt = GEMINI_TRANSCRIBE_PROMPT
        if context:
            prompt += f"\n\nآخر ما فُرِّغ قبل هذا المقطع (سياق فقط — لا تُعده في مخرجاتك): {context}"
        part = types.Part.from_bytes(data=pcm_to_wav(pcm, self._sample_rate), mime_type="audio/wav")
        return self._generate([part], prompt)

    def transcribe_file(self, path: str) -> str:
        from pathlib import Path

        from google.genai import types

        file_path = Path(path)
        if not file_path.exists():
            return ""
        mime = _AUDIO_MIME_BY_SUFFIX.get(file_path.suffix.lower(), "audio/wav")
        part = types.Part.from_bytes(data=file_path.read_bytes(), mime_type=mime)
        return self._generate([part], GEMINI_TRANSCRIBE_PROMPT)


class WhisperSTTEngine(STTEngine):
    """faster-whisper small CPU int8 — يتطلب حزمة اختيارية [whisper]."""

    def __init__(self) -> None:
        from faster_whisper import WhisperModel  # استيراد كسول — الحزمة اختيارية

        self._model = WhisperModel("small", device="cpu", compute_type="int8")
        self._buffers: dict[str, bytearray] = {}

    def stream_chunk(self, session_id: str, seq: int, payload_b64: str) -> Iterator[STTSegment]:
        import base64

        buffer = self._buffers.setdefault(session_id, bytearray())
        buffer.extend(base64.b64decode(payload_b64))
        # تفريغ تدريجي كل ~2 ثانية صوت (NFR-01) — تبسيط: تفريغ الملف المتراكم
        if seq % 8 == 7:
            import io
            segments, _info = self._model.transcribe(io.BytesIO(bytes(buffer)), language="ar")
            for segment in segments:
                yield STTSegment(text=segment.text.strip(), t0=segment.start, t1=segment.end, is_final=True)

    def transcribe_file(self, path: str) -> str:
        segments, _info = self._model.transcribe(path, language="ar")
        return " ".join(segment.text.strip() for segment in segments)


_stt_instance: STTEngine | None = None


def get_stt() -> STTEngine:
    global _stt_instance
    if _stt_instance is None:
        s = get_settings()
        if s.stt_engine == "gemini":
            if not s.gemini_api_key:
                logger.warning("STT_ENGINE=gemini لكن GEMINI_API_KEY غائب — تفعيل mock (D-04)")
                _stt_instance = MockSTTEngine()
            else:
                try:
                    _stt_instance = GeminiSTTEngine()
                except Exception as exc:  # حزمة/موارد غائبة → mock دون توقف (D-04)
                    logger.warning("تعذّر تشغيل GeminiSTTEngine (%s) — تفعيل mock", exc)
                    _stt_instance = MockSTTEngine()
        elif s.stt_engine == "whisper":
            try:
                _stt_instance = WhisperSTTEngine()
            except Exception:  # موارد غائبة → mock دون توقف (D-04)
                logger.warning("STT_ENGINE=whisper غير متاح — تفعيل mock")
                _stt_instance = MockSTTEngine()
        else:
            _stt_instance = MockSTTEngine()
    return _stt_instance


def reset_stt_cache() -> None:
    global _stt_instance
    _stt_instance = None
