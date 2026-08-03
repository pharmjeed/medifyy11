"""أرشفة الأرشيف القائم WAV → FLAC على دفعات (المرحلة 9 — اختياري، ليلي).

python scripts/archive_flac_backfill.py [--limit 200] [--dry-run]

يعالج تسجيلات ما بعد P1 (لها transcripts) فقط — تسجيل قيد الالتقاط لا يُمس.
التحقق الإلزامي داخل الخدمة: لا يُحذف WAV إلا بعد فك FLAC ومطابقة بصمة PCM.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db import system_session  # noqa: E402
from app.models import Recording, Transcript, Visit  # noqa: E402
from app.services.audio_archive import archive_recording_to_flac, ffmpeg_available  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200, help="حجم الدفعة الليلية")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not ffmpeg_available():
        print("ffmpeg غير متوفر — لا أرشفة")
        return 1

    converted = 0
    skipped = 0
    with system_session() as db:
        rows = db.execute(
            select(Visit)
            .join(Recording, Recording.visit_id == Visit.id)
            .join(Transcript, Transcript.visit_id == Visit.id)
            .where(
                Recording.deleted_at.is_(None),
                Recording.storage_uri.like("%.wav"),
            )
            .limit(args.limit)
        ).scalars().all()
        print(f"مرشحة للأرشفة: {len(rows)}")
        for visit in rows:
            if args.dry_run:
                skipped += 1
                continue
            if archive_recording_to_flac(db, visit):
                converted += 1
            else:
                skipped += 1
    print(f"أُرشفت: {converted} · تُركت: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
