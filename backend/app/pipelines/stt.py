"""محرك STT قابل للتبديل — STT_ENGINE=whisper|mock (P1 — DOC-08 §١).

mock: مولّد نص عربي سريري تجريبي متدفق — لا يوقف أي شيء عند غياب الموارد (D-04).
whisper: faster-whisper (small, CPU int8) داخل الحاوية.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

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
        if s.stt_engine == "whisper":
            try:
                _stt_instance = WhisperSTTEngine()
            except Exception:  # موارد غائبة → mock دون توقف (D-04)
                logger.warning("STT_ENGINE=whisper غير متاح — تفعيل mock")
                _stt_instance = MockSTTEngine()
        else:
            _stt_instance = MockSTTEngine()
    return _stt_instance
