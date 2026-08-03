"""سلامة ملف الصوت المتدفق (المرحلة 2 من التحصين) — سجل audio_chunks هو مصدر الحقيقة.

وظيفتان:
- reconcile_ledger: عند فتح قناة WS — مواءمة الملف مع السجل في الاتجاهين (انهيار وسط
  الكتابة أو وسط commit) ثم إعادة موضع الاستئناف المعمَّر عبر الاتصالات.
- verify_finalized_audio: عند recording/stop — لا-فجوات + مطابقة الحجم + bit-exact
  (بصمة كل مقطع تُقارن ببايتات الملف نفسها) قبل إطلاق P1؛ الفشل = MDF-4234 بقائمة الناقص.

الإزاحات مطلقة (بايتات PCM بعد الترويسة): زيارة سبقت 0012 قد تحمل بادئة صوت بلا صفوف
سجل — تُحترم كما هي (لا قصّ ولا تحقق عليها) والمقاطع الجديدة تُلحق بعدها بإزاحاتها.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import MedifyError
from ..models import AudioChunk, Recording, Visit

WAV_HEADER_BYTES = 44


def _header_bytes(path: Path) -> int:
    return WAV_HEADER_BYTES if path.suffix.lower() == ".wav" else 0


def reconcile_ledger(db: Session, visit_id: uuid.UUID, storage_uri: str) -> tuple[int, int]:
    """يعيد (آخر chunk_index مثبَّت، إزاحة الكتابة التالية بالبايت) بعد شفاء الملف/السجل.

    - سجل فارغ وملف فيه صوت: بادئة ما قبل 0012 — تُحترم، والكتابة تُكمل بعدها.
    - ملف أطول من نهاية السجل: كتابة جزئية قبل commit صفها — يُقصّ الذيل غير الموثّق.
    - سجل أطول من الملف: صفوف commit بلا بايتات (فقد ذيل الملف) — تُحذف صفوف الذيل.
    الاتجاهان نادران (انهيار لحظي) لكن تركهما يعني فساداً صامتاً في WAV النهائي.
    """
    path = Path(storage_uri)
    header = _header_bytes(path)
    rows = db.execute(
        select(AudioChunk).where(AudioChunk.visit_id == visit_id).order_by(AudioChunk.chunk_index)
    ).scalars().all()
    file_data = max(0, path.stat().st_size - header) if path.exists() else 0

    if not rows:
        # لا سجل: إما زيارة جديدة (ملف فارغ) أو بادئة قديمة — كلاهما يُكمل من نهاية الملف
        return -1, file_data

    ledger_end = rows[-1].byte_offset + rows[-1].byte_length
    if file_data > ledger_end:
        with path.open("r+b") as handle:
            handle.truncate(header + ledger_end)
    elif file_data < ledger_end:
        kept: list[AudioChunk] = []
        for row in rows:
            if row.byte_offset + row.byte_length <= file_data:
                kept.append(row)
            else:
                db.delete(row)
        db.flush()
        rows = kept
        ledger_end = (rows[-1].byte_offset + rows[-1].byte_length) if rows else 0
        if path.exists():
            with path.open("r+b") as handle:
                handle.truncate(header + ledger_end)

    last_index = rows[-1].chunk_index if rows else -1
    return last_index, ledger_end


def verify_finalized_audio(db: Session, visit: Visit) -> None:
    """تحقق finalize الصارم قبل P1 — زيارة بلا سجل مقاطع (ما قبل 0012) تمرّ بلا تحقق."""
    chunks = db.execute(
        select(AudioChunk).where(AudioChunk.visit_id == visit.id).order_by(AudioChunk.chunk_index)
    ).scalars().all()
    if not chunks:
        return  # توافق عكسي: زيارات سبقت سجل المقاطع

    indices = [chunk.chunk_index for chunk in chunks]
    missing = sorted(set(range(indices[-1] + 1)) - set(indices))
    if missing:
        raise MedifyError("MDF-4234", details={
            "reason": "missing_chunks",
            "missing_chunks": missing[:50],
            "missing_count": len(missing),
        })

    recording = db.execute(select(Recording).where(Recording.visit_id == visit.id)).scalar_one_or_none()
    if recording is None:
        raise MedifyError("MDF-4234", details={"reason": "recording_row_missing"})
    path = Path(recording.storage_uri)
    header = _header_bytes(path)
    # الحجم بنهاية آخر مقطع (الإزاحات مطلقة — تحتمل بادئة ما قبل السجل)
    expected = header + chunks[-1].byte_offset + chunks[-1].byte_length
    actual = path.stat().st_size if path.exists() else 0
    if actual != expected:
        raise MedifyError("MDF-4234", details={
            "reason": "size_mismatch", "expected_bytes": expected, "actual_bytes": actual,
        })

    # bit-exact: بصمة كل مقطع تُقارن ببايتات الملف في إزاحته المطلقة
    with path.open("rb") as handle:
        for chunk in chunks:
            handle.seek(header + chunk.byte_offset)
            data = handle.read(chunk.byte_length)
            if hashlib.sha256(data).hexdigest() != chunk.sha256:
                raise MedifyError("MDF-4234", details={
                    "reason": "checksum_mismatch", "chunk_index": chunk.chunk_index,
                })
