"""مصنّف أخطاء خطوط المعالجة (المرحلة 3 من التحصين).

retryable: انقطاعات عابرة (timeout / اتصال / 5xx / rate-limit) — تستحق إعادة بتباعد.
non_retryable: عيوب ثابتة (ملف تالف / صيغة غير مدعومة / صوت فارغ / مخرج غير مطابق) —
الإعادة عبث؛ MDF فوراً بمحاولة واحدة.

الافتراضي عند الغموض: non_retryable — فشل سريع بإشعار أوضح خير من ثلاث محاولات صمّاء.
"""
from __future__ import annotations

import wave

RETRYABLE = "retryable"
NON_RETRYABLE = "non_retryable"

# عيوب الملف/الصيغة الثابتة — تُفحص قبل أنماط الشبكة (FileNotFoundError من عائلة OSError
# التي كان المصنّف النصي القديم يعدّها عابرة خطأً)
_NON_RETRYABLE_TYPES: tuple[type[BaseException], ...] = (
    wave.Error,
    EOFError,
    FileNotFoundError,
    IsADirectoryError,
    PermissionError,
    ValueError,  # صيغة/محتوى غير صالح من المكتبات الصوتية
)
_NON_RETRYABLE_MARKERS = (
    "riff", "not a wav", "unsupported format", "unsupported audio", "invalid audio",
    "corrupt", "empty audio", "no audio", "zero-length", "decode error", "decoder",
    "invalid api key", "api key not valid", "unauthorized", "permission denied",
)

_RETRYABLE_TYPES_BY_NAME = ("Timeout", "Connection", "Network", "TooManyRequests",
                            "ServiceUnavailable", "InternalServerError", "APIConnection")
_RETRYABLE_MARKERS = (
    "timeout", "timed out", "connection", "refused", "reset", "temporarily",
    "500", "502", "503", "504", "429", "too many requests", "rate limit",
    "service unavailable", "resource_exhausted", "overloaded", "cuda out of memory",
)


def classify_error(exc: BaseException) -> str:
    """retryable | non_retryable — الأنواع الصريحة أولاً ثم أنماط الاسم/النص."""
    if isinstance(exc, _NON_RETRYABLE_TYPES):
        return NON_RETRYABLE

    text = str(exc).lower()
    if any(marker in text for marker in _NON_RETRYABLE_MARKERS):
        return NON_RETRYABLE

    name = exc.__class__.__name__
    if any(part in name for part in _RETRYABLE_TYPES_BY_NAME):
        return RETRYABLE
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return RETRYABLE  # بعد استبعاد عائلة الملفات أعلاه — المتبقي شبكي غالباً
    if any(marker in text for marker in _RETRYABLE_MARKERS):
        return RETRYABLE

    return NON_RETRYABLE
