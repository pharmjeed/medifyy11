#!/usr/bin/env python
"""تنفيذ سياسة الاحتفاظ بالصوت — يُشغَّل دورياً (A4، توجيه المالك 2026-07-22).

    python scripts/purge_recordings.py            # حذف فعلي
    python scripts/purge_recordings.py --dry-run  # عرض ما سيُحذف بلا حذف

يعمل بجلسة نظام (دور المالك) لأنه لا فاعل بشري له ولا سياق منشأة واحدة.
كل عملية حذف تُدوَّن في audit_logs، وأدمن كل منشأة يُشعَر بـ ad.retention_purge.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db import system_session  # noqa: E402
from app.services.retention import purge_expired_recordings  # noqa: E402


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    with system_session() as db:  # يُودِع عند الخروج بلا استثناء
        result = purge_expired_recordings(db, dry_run=dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
