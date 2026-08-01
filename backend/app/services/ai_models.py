"""اختيار نموذج قوقل من المنصة (توجيه مالك 2026-08-01).

- الاختيار يُخزَّن في platform_settings بمفتاح ai.gemini_model ويتجاوز GEMINI_MODEL البيئي.
- قائمة النماذج تُجلب حيّة من Google API (models.list) عند توفر المفتاح — وإلا كتالوج احتياطي ثابت.
- المحركات (llm/stt) تقرأ الاختيار عند البناء فقط — تبديل الاختيار يعيد بناءها (reset caches).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import PlatformSetting

logger = logging.getLogger("medify.sa")

AI_MODEL_KEY = "ai.gemini_model"

# كتالوج احتياطي عند غياب GEMINI_API_KEY أو تعذر الجلب — القائمة الحيّة هي المصدر الأول دائماً
GOOGLE_MODEL_FALLBACK: list[dict[str, str]] = [
    {"id": "gemini-3.6-pro", "display_name": "Gemini 3.6 Pro", "description": "الأقوى — استدلال معمّق وتكلفة أعلى"},
    {"id": "gemini-3.6-flash", "display_name": "Gemini 3.6 Flash", "description": "توازن سرعة/جودة للأحمال العامة"},
    {"id": "gemini-3.5-pro", "display_name": "Gemini 3.5 Pro", "description": "جيل سابق — جودة عالية"},
    {"id": "gemini-3.5-flash", "display_name": "Gemini 3.5 Flash", "description": "جيل سابق — سريع ومتعدد الوسائط"},
    {"id": "gemini-3.5-flash-lite", "display_name": "Gemini 3.5 Flash-Lite", "description": "الأخف كلفة — الافتراضي الحالي"},
    {"id": "gemini-2.5-pro", "display_name": "Gemini 2.5 Pro", "description": "قديم — للحسابات المفعّل عليها فقط"},
    {"id": "gemini-2.5-flash", "display_name": "Gemini 2.5 Flash", "description": "قديم — أُغلق لحسابات جديدة 2026-07"},
    {"id": "gemini-2.5-flash-lite", "display_name": "Gemini 2.5 Flash-Lite", "description": "قديم — الأخف في جيل 2.5"},
]

_LIVE_CACHE_TTL = 600.0  # ثوانٍ — نتجنب استدعاء models.list مع كل فتح للصفحة
_live_cache: tuple[float, list[dict[str, str]]] | None = None


def stored_gemini_model(db: Session) -> str | None:
    """الاختيار المخزَّن في platform_settings — None = لا تجاوز (يسري افتراضي البيئة)."""
    row = db.execute(
        select(PlatformSetting).where(PlatformSetting.key == AI_MODEL_KEY)
    ).scalar_one_or_none()
    if row is None or not isinstance(row.value, dict):
        return None
    model = row.value.get("model")
    return model if isinstance(model, str) and model else None


def set_gemini_model(db: Session, model: str | None, admin_id: Any = None) -> None:
    """يخزّن الاختيار (None = حذف التجاوز والعودة لافتراضي البيئة)."""
    row = db.execute(
        select(PlatformSetting).where(PlatformSetting.key == AI_MODEL_KEY)
    ).scalar_one_or_none()
    if model is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(PlatformSetting(key=AI_MODEL_KEY, value={"model": model}, updated_by=admin_id))
    else:
        row.value = {"model": model}
        row.updated_by = admin_id


def resolve_gemini_model() -> str:
    """النموذج الفعلي للمحركات: تجاوز المنصة إن وُجد وإلا GEMINI_MODEL البيئي.

    تُستدعى عند بناء المحرك فقط (النتيجة تعيش مع كائن المحرك حتى reset) — بجلسة نظام خاصة.
    أي تعذر قراءة (جدول لم يُهاجَر بعد/قاعدة غير متاحة) = الافتراضي البيئي دون توقف (نمط D-03).
    """
    override: str | None = None
    try:
        from ..db import system_session

        with system_session() as db:
            override = stored_gemini_model(db)
    except Exception as exc:
        logger.warning("تعذّرت قراءة تجاوز نموذج المنصة (%s) — يسري افتراضي البيئة", exc)
    return override or get_settings().gemini_model


def list_google_models() -> tuple[list[dict[str, str]], str]:
    """(القائمة، المصدر live|fallback) — كل نماذج الحساب الداعمة لتوليد المحتوى."""
    global _live_cache
    s = get_settings()
    if not s.gemini_api_key:
        return GOOGLE_MODEL_FALLBACK, "fallback"
    if _live_cache is not None and time.monotonic() - _live_cache[0] < _LIVE_CACHE_TTL:
        return _live_cache[1], "live"
    try:
        from google import genai  # استيراد كسول — الحزمة اختيارية على بيئات الـmock

        client = genai.Client(api_key=s.gemini_api_key)
        models: list[dict[str, str]] = []
        for model in client.models.list():
            actions = getattr(model, "supported_actions", None) or []
            if actions and "generateContent" not in actions:
                continue
            model_id = (model.name or "").removeprefix("models/")
            if not model_id:
                continue
            models.append({
                "id": model_id,
                "display_name": getattr(model, "display_name", None) or model_id,
                "description": getattr(model, "description", None) or "",
            })
        if not models:
            return GOOGLE_MODEL_FALLBACK, "fallback"
        _live_cache = (time.monotonic(), models)
        return models, "live"
    except Exception as exc:
        logger.warning("تعذّر جلب قائمة نماذج قوقل (%s) — الكتالوج الاحتياطي", exc)
        return GOOGLE_MODEL_FALLBACK, "fallback"
