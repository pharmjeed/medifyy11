"""السند المرتبط (م10) — جملة المذكرة ↔ مقاطع الصوت/التفريغ التي تسندها.

التخزين JSONB مشفّر على summary_sections.evidence_json (لا جدول مستقل): البيانات
تُقرأ دائماً مع قسمها، لا تُستعلم عبر الزيارات، وحجمها جُمَل معدودة — عمود مضمّن
أرخص وأبسط من join إضافي على كل عرض للمراجعة (المبرَّر في PROGRESS م10).

بنية العنصر الواحد:
{"text", "segment_ids": [..], "audio_start_ms", "audio_end_ms", "origin": "ai"|"doctor"}
- segment_ids فارغة = «بلا مصدر صوتي» (مثل [Not discussed]) — وسم خافت في الواجهة.
- origin="doctor" = جملة عُدّلت/أُضيفت يدوياً بعد التوليد — وسم «تحرير طبيب».
"""
from __future__ import annotations

import re

from ..models import SummarySection

_SENTENCE_SPLIT = re.compile(r"(?<=[.!؟?])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def build_section_evidence(sentences: list[dict], segments_by_id: dict[str, dict]) -> list[dict]:
    """من مخرج P2-verify@1.1 إلى عناصر السند المخزّنة — الأزمنة من مقاطع P1 (ms)."""
    entries: list[dict] = []
    for sentence in sentences:
        if not isinstance(sentence, dict):
            continue
        text = str(sentence.get("text", "")).strip()
        if not text:
            continue
        segment_ids = [
            sid for sid in (sentence.get("segment_ids") or [])
            if isinstance(sid, str) and sid in segments_by_id  # لا معرّفات مخترعة
        ]
        start_ms: int | None = None
        end_ms: int | None = None
        confidence: float | None = None
        if segment_ids:
            starts = [segments_by_id[sid].get("t0", 0.0) for sid in segment_ids]
            ends = [segments_by_id[sid].get("t1", 0.0) for sid in segment_ids]
            start_ms = int(min(starts) * 1000)
            end_ms = int(max(ends) * 1000)
            # م11: ثقة الجملة = أدنى ثقة بين مقاطعها المصدرية — تشاؤم مقصود
            values = [
                segments_by_id[sid].get("confidence")
                for sid in segment_ids
                if isinstance(segments_by_id[sid].get("confidence"), (int, float))
            ]
            if values:
                confidence = round(min(values), 3)
        entries.append({
            "text": text,
            "segment_ids": segment_ids,
            "audio_start_ms": start_ms,
            "audio_end_ms": end_ms,
            "origin": "ai",
            "confidence": confidence,
        })
    return entries


def refresh_section_evidence(section: SummarySection) -> None:
    """بعد أي تعديل (كتابة/إملاء/محادثة AI): الجمل الباقية تحتفظ بسندها، والجديدة
    أو المعدّلة تُوسم «تحرير طبيب» بلا مصدر صوتي — معيار القبول م10."""
    existing = {
        _normalize(entry.get("text", "")): entry
        for entry in (section.evidence_json or [])
        if isinstance(entry, dict)
    }
    rebuilt: list[dict] = []
    for sentence in split_sentences(section.content_current):
        entry = existing.get(_normalize(sentence))
        if entry is not None:
            rebuilt.append(entry)
        else:
            rebuilt.append({
                "text": sentence,
                "segment_ids": [],
                "audio_start_ms": None,
                "audio_end_ms": None,
                "origin": "doctor",
                "confidence": None,
            })
    section.evidence_json = rebuilt
