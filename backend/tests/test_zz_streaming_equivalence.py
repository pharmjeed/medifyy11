"""المرحلة 18 — جاهزية Streaming: اختبار التكافؤ (الأهم).

نفس الملف عبر المسار القديم (المرجع المحفوظ قبل الـrefactor) والجديد → تفريغ
متطابق حرفياً | تغذية المقاطع واحداً واحداً بفواصل = نتيجة الدفعة | صفر تغيير
في API أو تجربة المستخدم (بقية الحزمة تمر بلا تعديل).

المرجع الذهبي مُولَّد من تشغيل المسار القديم قبل الـrefactor ومخزَّن في
tests/fixtures/streaming_reference.json — أي انحراف في التفريغ يكسر هذا الاختبار.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REFERENCE_PATH = Path(__file__).parent / "fixtures" / "streaming_reference.json"


@pytest.fixture(scope="module")
def golden_reference() -> dict:
    assert REFERENCE_PATH.exists(), (
        "المرجع الذهبي مفقود — يُولَّد بـ scripts/capture_stt_reference.py قبل أي refactor"
    )
    return json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))


def test_batch_matches_saved_reference(golden_reference):
    """المسار الحالي (بعد الـrefactor) ينتج تفريغ المرجع حرفياً — لا انحراف."""
    from app.pipelines.stt import get_stt, reset_stt_cache

    reset_stt_cache()
    segments = get_stt().transcribe_visit(golden_reference["audio_path"])
    assert segments == golden_reference["segments"], "المخرج انحرف عن المرجع المحفوظ"


def test_streaming_feed_equals_batch(golden_reference):
    """تغذية المقاطع واحداً واحداً عبر الواجهة المتدفقة = نتيجة الدفعة حرفياً."""
    from app.pipelines.streaming import TranscriptionStream

    stream = TranscriptionStream(golden_reference["audio_path"])
    emitted: list[dict] = []
    for chunk in golden_reference["chunks"]:
        emitted.extend(stream.feed(chunk))
    emitted.extend(stream.finalize())
    assert emitted == golden_reference["segments"], "المسار المتدفق يخالف الدفعة"


def test_batch_mode_is_special_case_of_stream(golden_reference):
    """الوضع الحالي batch = حالة خاصة: كل المقاطع دفعةً ثم finalize."""
    from app.pipelines.streaming import stream_from_ledger, transcribe_batch

    batch = transcribe_batch(golden_reference["audio_path"])
    streamed = stream_from_ledger(golden_reference["audio_path"], golden_reference["chunks"])
    assert streamed == batch, "التغذية من السجل تطابق الدفعة"
    assert batch == golden_reference["segments"]


def test_incremental_summary_input_finalizes_identically(golden_reference):
    """P2 يقبل تفريغاً متزايداً (append) مع نقطة finalize — النتيجة نفسها."""
    from app.pipelines.streaming import IncrementalTranscript

    incremental = IncrementalTranscript()
    for segment in golden_reference["segments"]:
        incremental.append(segment)
    assert incremental.finalize() == {"segments": golden_reference["segments"]}

    at_once = IncrementalTranscript()
    at_once.extend(golden_reference["segments"])
    assert at_once.finalize() == incremental.finalize()
