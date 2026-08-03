"""أرشفة الصوت WAV → FLAC بعد نجاح P1 (المرحلة 9) — ضغط بلا فقد بتحقق إلزامي.

القاعدة الحاكمة: لا يُحذف WAV الأصلي إلا بعد فك الـFLAC ومطابقة sha256 لعينات
PCM حرفياً. فشل المطابقة = إبقاء WAV + حذف الناتج + إنذار (Audit + سجل أخطاء).
المتصفحات الحديثة تشغّل FLAC أصلاً — مراجع التخزين تتحدث لتشير للملف الجديد،
وسياسة الاحتفاظ (م8) تتلف storage_uri أياً كانت صيغته.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import wave
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import Recording, Visit

logger = logging.getLogger("medify.audio_archive")

_FFMPEG_TIMEOUT = 600  # استشارة طويلة جداً ≈ دقائق تحويل قليلة — سقف 10 دقائق


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _wav_pcm_hash(path: Path) -> str:
    """بصمة عينات PCM من حاوية WAV (لا بايتات الملف — الترويسة خارج المقارنة)."""
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    return hashlib.sha256(frames).hexdigest()


def _decoded_pcm_hash(path: Path) -> str:
    """فك أي حاوية (FLAC هنا) إلى PCM خام s16le أحادي القناة عبر ffmpeg وبصمه."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        capture_output=True, timeout=_FFMPEG_TIMEOUT, check=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def archive_recording_to_flac(db: Session, visit: Visit) -> bool:
    """يحوّل تسجيل الزيارة إلى FLAC ويحدّث storage_uri — True عند اكتمال الأرشفة.

    آمنة النداء دوماً: غياب ffmpeg/الملف أو أرشفة سابقة = لا فعل. أي فشل لا يمس
    الأصل إطلاقاً — الأسوأ الممكن بقاء WAV كما كان.
    """
    if not ffmpeg_available():
        return False
    recording = db.execute(select(Recording).where(Recording.visit_id == visit.id)).scalar_one_or_none()
    if recording is None or recording.deleted_at is not None:
        return False
    wav_path = Path(recording.storage_uri)
    if wav_path.suffix.lower() != ".wav" or not wav_path.exists():
        return False

    flac_path = wav_path.with_suffix(".flac")
    try:
        original_hash = _wav_pcm_hash(wav_path)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(wav_path), "-c:a", "flac", str(flac_path)],
            capture_output=True, timeout=_FFMPEG_TIMEOUT, check=True,
        )
        decoded_hash = _decoded_pcm_hash(flac_path)
    except (subprocess.SubprocessError, OSError, wave.Error, EOFError) as exc:
        logger.error("أرشفة FLAC تعذّرت للزيارة %s: %s — WAV باقٍ", visit.id, exc)
        flac_path.unlink(missing_ok=True)
        return False

    if decoded_hash != original_hash:
        # فشل المطابقة: الأصل لا يُمس + إنذار — الأرشفة تُعاد في دفعة لاحقة أو يدوياً
        flac_path.unlink(missing_ok=True)
        logger.error("إنذار: فك FLAC لا يطابق أصل WAV للزيارة %s — أُبقي الأصل", visit.id)
        audit(db, visit.facility_id, "recording.flac_verify_failed", "recording", recording.id, None,
              {"visit_id": str(visit.id)})
        db.flush()
        return False

    wav_size = wav_path.stat().st_size
    flac_size = flac_path.stat().st_size
    recording.storage_uri = str(flac_path)
    db.flush()
    wav_path.unlink(missing_ok=True)
    audit(db, visit.facility_id, "recording.archived_flac", "recording", recording.id, None,
          {"wav_bytes": wav_size, "flac_bytes": flac_size,
           "saved_pct": round(100 * (1 - flac_size / wav_size)) if wav_size else 0})
    db.flush()
    logger.info("أرشفة FLAC للزيارة %s: %d → %d بايت", visit.id, wav_size, flac_size)
    return True
