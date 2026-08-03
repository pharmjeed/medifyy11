"""جاهزية Streaming (م18) — إعادة تشكيل P1 بلا أي ميزة مرئية.

كان: «ملف كامل → تفريغ كامل». صار: واجهة تستهلك مقاطع صوتية مرتّبة وتُصدر مقاطع
تفريغ — والوضع الحالي batch حالة خاصة منها (تغذية كل المقاطع ثم finalize بنتيجة
مطابقة تماماً، يثبتها اختبار التكافؤ ضد مرجع محفوظ قبل الـrefactor).

الاختيار: consumer متزامن (generator) لا طابور مستقل — المبرَّر:
- وحدة التدفق هنا هي نفسها وحدة م2 (chunk = 250ms من audio_chunks)، والمقاطع
  تصل عبر قناة WS القائمة لا عبر broker؛ إدخال طابور ثانٍ يضاعف نقاط الفشل بلا
  مقابل ما دام محرك STT الحالي لا يقبل تغذية جزئية.
- عامل arq (م3) يبقى حامل التنفيذ خارج الطلب — الواجهة هنا داخل مهمته لا بديلاً عنها.
عند وصول محرك يدعم البث الحقيقي يكفي استبدال `_flush` بمكالمة تدفقية — بلا مساس
بالمستدعين ولا بالـAPI.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from . import stt as stt_module

logger = logging.getLogger("medify.streaming")


class TranscriptionStream:
    """يستهلك مقاطع صوت مرتّبة ويُصدر مقاطع تفريغ.

    العقد: feed(chunk) يعيد ما نضج من مقاطع تفريغ (قد تكون فارغة)، وfinalize()
    يعيد الباقي. المجموع = تفريغ الملف كاملاً حرفياً (تكافؤ الدفعة).
    """

    def __init__(self, audio_path: str | None = None) -> None:
        self._audio_path = audio_path
        self._chunks: list[dict[str, Any]] = []
        self._finalized = False

    def feed(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        """تغذية مقطع صوتي (وحدة م2 نفسها) — المحرك الحالي لا ينضج جزئياً فتعود فارغة."""
        if self._finalized:
            raise RuntimeError("TranscriptionStream: feed بعد finalize")
        self._chunks.append(chunk)
        return []

    def extend(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for chunk in chunks:
            out.extend(self.feed(chunk))
        return out

    def finalize(self) -> list[dict[str, Any]]:
        """نقطة الإنهاء — تُصدر كل ما تبقّى (الآن: التفريغ كاملاً)."""
        if self._finalized:
            return []
        self._finalized = True
        path = self._audio_path or self._path_from_chunks()
        if not path:
            return []
        # الوصول عبر الوحدة لا بالاستيراد المباشر — يُبقي مقبس المحرك واحداً قابلاً للاستبدال
        return stt_module.get_stt().transcribe_visit(path)

    def _path_from_chunks(self) -> str | None:
        for chunk in self._chunks:
            if chunk.get("audio_path"):
                return str(chunk["audio_path"])
        return None

    def __iter__(self) -> Iterator[dict[str, Any]]:
        yield from self.finalize()


def transcribe_batch(audio_path: str) -> list[dict[str, Any]]:
    """الوضع الحالي — حالة خاصة من التدفق: تغذية ثم finalize."""
    stream = TranscriptionStream(audio_path)
    return stream.finalize()


def stream_from_ledger(audio_path: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """تغذية من سجل audio_chunks (م2) — وحدة التدفق موحّدة بين المرحلتين."""
    stream = TranscriptionStream(audio_path)
    emitted = stream.extend(chunks)
    emitted.extend(stream.finalize())
    return emitted


class IncrementalTranscript:
    """مدخل P2 المتزايد (append) مع نقطة finalize — تُستدعى مباشرةً اليوم.

    يسمح لاحقاً ببناء الملخص على تفريغ ينمو، بلا تغيير في عقد run_summary.
    """

    def __init__(self) -> None:
        self._segments: list[dict[str, Any]] = []

    def append(self, segment: dict[str, Any]) -> None:
        self._segments.append(segment)

    def extend(self, segments: list[dict[str, Any]]) -> None:
        self._segments.extend(segments)

    @property
    def segments(self) -> list[dict[str, Any]]:
        return list(self._segments)

    def finalize(self) -> dict[str, Any]:
        return {"segments": list(self._segments)}
