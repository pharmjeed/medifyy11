"""محرك STT قابل للتبديل — STT_ENGINE=gemini|whisper|mock (P1 — DOC-08 §١ المعدّل بقرار مالك 2026-08-02).

لا تفريغ أثناء التسجيل: الصوت يُجمع ملف WAV أولاً بأول عبر قناة الزيارة، وبعد إنهاء
المحادثة يُفرَّغ الملف الكامل تمريرة واحدة — فيقرأ المحرك السياق كله (لا أخطاء حدود
نوافذ) ويُسنَد المتحدث من كامل المحادثة لا من مقاطع معزولة.

mock: حوار عربي سريري تجريبي — لا يوقف أي شيء عند غياب الموارد (D-04).
gemini: تفريغ الملف الكامل + تحديد المتحدث (diarization) بمخرج JSON متعدد الوسائط.
whisper: faster-whisper (small, CPU int8) — بلا متحدث؛ يُسند لغوياً من كامل المحادثة.
"""
from __future__ import annotations

import io
import json
import logging
import re
import wave
from abc import ABC, abstractmethod
from pathlib import Path

from ..config import get_settings

logger = logging.getLogger("medify.pipelines")


class STTEngine(ABC):
    @abstractmethod
    def transcribe_visit(self, path: str) -> list[dict]:
        """تفريغ ملف الزيارة الكامل بعد إنهاء المحادثة — مقاطع {text, t0, t1[, speaker]}.

        المحرك الذي يميّز المتحدث صوتياً يعيد speaker ∈ {doctor, patient}؛ غيره يتركه
        فيُسند لغوياً من كامل المحادثة (pipelines.speaker). ملف غائب/صامت = قائمة فارغة —
        لا يُختلق كلام لم يُقَل.
        """

    @abstractmethod
    def transcribe_file(self, path: str) -> str:
        """مسار قصير غير متدفق — إملاء التحرير الصوتي (FR-706)."""


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """يغلّف PCM16 أحادي بترويسة WAV — الصيغة التي تُخزَّن بها التسجيلات وتقبلها نماذج الصوت."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


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
    """يعيد حوار العرض الكامل بطوابع زمنية — المتحدث يُسند لغوياً في P1 كبقية المحركات غير المميِّزة."""

    SENTENCE_SECONDS = 4.0

    def transcribe_visit(self, path: str) -> list[dict]:
        return [
            {
                "id": f"s-{index}",
                "text": text,
                "t0": round(index * self.SENTENCE_SECONDS, 2),
                "t1": round(index * self.SENTENCE_SECONDS + 3.5, 2),
            }
            for index, text in enumerate(MOCK_DIALOGUE)
        ]

    def transcribe_file(self, path: str) -> str:
        return "Patient advised to continue current plan and return if symptoms worsen."


GEMINI_TRANSCRIBE_PROMPT = (
    "أنت محرك تفريغ صوتي طبي داخل عيادة سعودية. فرّغ الكلام في المقطع الصوتي حرفياً كما نُطق.\n"
    "- العربية بلهجاتها تُكتب عربية، والمصطلحات والأدوية الإنجليزية تُكتب لاتينية كما نُطقت.\n"
    "- لا تترجم، ولا تلخّص، ولا تصحّح، ولا تضف أي تعليق أو وصف للأصوات أو ترقيماً للمتحدثين.\n"
    "- إن لم يكن في المقطع كلام مسموع فأعد نصاً فارغاً تماماً.\n"
    "أعد نص التفريغ فقط بلا أي مقدمة."
)

# تفريغ المحادثة الكاملة + تمييز المتحدث من كامل السياق (قرار مالك 2026-08-02)
GEMINI_DIARIZE_PROMPT = (
    "أنت محرك تفريغ صوتي طبي لمحادثة كاملة بين طبيب ومريض داخل عيادة سعودية.\n"
    "فرّغ الكلام حرفياً كما نُطق، وقسّمه مقاطع عند تبادل الأدوار:\n"
    "- العربية بلهجاتها تُكتب عربية، والمصطلحات والأدوية الإنجليزية تُكتب لاتينية كما نُطقت.\n"
    "- لا تترجم، ولا تلخّص، ولا تصحّح، ولا تضف كلاماً لم يُقَل.\n"
    "- حدد متحدث كل مقطع (doctor أو patient) بالاستناد إلى الصوت وسياق المحادثة كاملة،\n"
    "  ومعه confidence بين 0 و1 لثقتك في الإسناد.\n"
    "- t0 وt1 زمن بداية المقطع ونهايته بالثواني من بداية التسجيل.\n"
    'أعد JSON فقط بالشكل: {"segments": [{"speaker": "doctor", "text": "...", "t0": 0.0, "t1": 3.5, "confidence": 0.95}]}\n'
    'إن لم يكن في التسجيل كلام مسموع أعد {"segments": []}.'
)

_AUDIO_MIME_BY_SUFFIX = {
    ".wav": "audio/wav", ".mp3": "audio/mp3", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac", ".aiff": "audio/aiff",
}


def _extract_segments_json(raw: str) -> list[dict]:
    """يقرأ {"segments": [...]} من رد النموذج — ValueError إن غاب الشكل المتعاقد عليه."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in diarization output")
    data = json.loads(match.group(0))
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise ValueError("diarization output missing segments list")
    return segments


class GeminiSTTEngine(STTEngine):
    """تفريغ الملف الكامل بعد الإنهاء — تمريرة واحدة متعددة الوسائط بمخرج JSON مقسّم بالمتحدثين."""

    def __init__(self) -> None:
        from google import genai  # استيراد كسول — الحزمة اختيارية على بيئات الـmock

        from ..services.ai_models import resolve_gemini_model

        settings = get_settings()
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_stt_model or resolve_gemini_model()

    # ----- الاستدعاء -----

    def _generate(self, parts: list, prompt: str) -> str:
        from google.genai import types

        content = types.Content(role="user", parts=[*parts, types.Part.from_text(text=prompt)])
        last_error: Exception | None = None
        for attempt in range(2):  # فشل عابر → إعادة واحدة قبل رفع MDF-5031 من طبقة الإيقاف
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

    def _audio_part(self, file_path: Path):
        from google.genai import types

        mime = _AUDIO_MIME_BY_SUFFIX.get(file_path.suffix.lower(), "audio/wav")
        return types.Part.from_bytes(data=file_path.read_bytes(), mime_type=mime)

    def transcribe_visit(self, path: str) -> list[dict]:
        file_path = Path(path)
        if not file_path.exists():
            return []
        part = self._audio_part(file_path)
        last_error: Exception | None = None
        for attempt in range(2):  # مخرج غير مطابق للعقد → إعادة استدعاء واحدة (نمط DOC-08 §٦)
            raw = self._generate([part], GEMINI_DIARIZE_PROMPT)
            try:
                return self._normalize(_extract_segments_json(raw))
            except ValueError as exc:
                last_error = exc
                logger.warning("Gemini diarization — مخرج غير مطابق (محاولة %s): %s", attempt + 1, exc)
        raise RuntimeError(f"Gemini diarization failed: {last_error}")

    @staticmethod
    def _normalize(raw_segments: list[dict]) -> list[dict]:
        """يقصّ المخرج على العقد: نص غير فارغ، متحدث قانوني إن وُجد، أزمنة عددية متصاعدة."""
        segments: list[dict] = []
        clock = 0.0
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            try:
                t0 = float(item["t0"])
                t1 = float(item["t1"])
            except (KeyError, TypeError, ValueError):
                t0 = clock
                t1 = clock
            clock = max(clock, t1)
            segment: dict = {"id": f"s-{len(segments)}", "text": text, "t0": round(t0, 2), "t1": round(t1, 2)}
            if item.get("speaker") in ("doctor", "patient"):
                segment["speaker"] = item["speaker"]
                try:
                    confidence = float(item["confidence"])
                    segment["speaker_confidence"] = round(min(0.99, max(0.0, confidence)), 2)
                except (KeyError, TypeError, ValueError):
                    pass
            segments.append(segment)
        return segments

    def transcribe_file(self, path: str) -> str:
        file_path = Path(path)
        if not file_path.exists():
            return ""
        return self._generate([self._audio_part(file_path)], GEMINI_TRANSCRIBE_PROMPT)


class WhisperSTTEngine(STTEngine):
    """faster-whisper small CPU int8 — يتطلب حزمة اختيارية [whisper]. بلا تمييز متحدث."""

    def __init__(self) -> None:
        from faster_whisper import WhisperModel  # استيراد كسول — الحزمة اختيارية

        self._model = WhisperModel("small", device="cpu", compute_type="int8")

    def transcribe_visit(self, path: str) -> list[dict]:
        if not Path(path).exists():
            return []
        segments, _info = self._model.transcribe(path, language="ar")
        spoken = [segment for segment in segments if segment.text.strip()]
        return [
            {"id": f"s-{index}", "text": segment.text.strip(), "t0": round(segment.start, 2), "t1": round(segment.end, 2)}
            for index, segment in enumerate(spoken)
        ]

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
