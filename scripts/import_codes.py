"""استيراد السجل المرجعي للأكواد (CLI) — قرار مالك 2026-08-02.

غلاف سطر أوامر حول app/services/registry_import.py — نفس المنطق الذي تستخدمه
صفحة السوبر أدمن «ملفات الأكواد» (/sa/registry). يعمل بدور المالك (دور التطبيق SELECT فقط).

الاستخدام:
    python scripts/import_codes.py --file SBS_V2_Code_list.xlsx --system SBS --version "SBS V2.0"
    python scripts/import_codes.py --file icd10am.csv --system ICD10AM --version "ICD-10-AM 12th ed."

تنبيه المصادر: SBS يُنزَّل من chi.gov.sa · ICD-10-AM مرخّص (IHACPA) عبر قنوات CHI/nphies.
**لا يُستورد ICD-10-CM الأمريكي ولا DRG — nphies يعتمد ICD-10-AM وSBS حصراً.**
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.registry_import import (  # noqa: E402
    REGISTRY_SYSTEMS,
    import_codes,
    parse_registry_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="استيراد السجل المرجعي للأكواد")
    parser.add_argument("--file", required=True, help="ملف xlsx (CHI) أو csv عام")
    parser.add_argument("--system", required=True, choices=list(REGISTRY_SYSTEMS))
    parser.add_argument("--version", required=True, help='إصدار السجل، مثل "SBS V2.0"')
    parser.add_argument("--sheet", default=None, help="اسم تبويب xlsx (الافتراضي: اكتشاف Technical List)")
    parser.add_argument("--dry-run", action="store_true", help="عدّ بلا كتابة")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"الملف غير موجود: {path}")
    try:
        rows = parse_registry_file(path.name, path.read_bytes(), args.sheet)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    settings = get_settings()
    url = os.environ.get("MIGRATIONS_DATABASE_URL") or settings.migrations_database_url or settings.database_url
    engine = create_engine(url)
    with Session(engine) as db:
        try:
            inserted, updated = import_codes(db, args.system, args.version, rows)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if args.dry_run:
            db.rollback()
            print(f"dry-run: كان سيُدخل {inserted} ويحدّث {updated} — {args.system} {args.version}")
        else:
            db.commit()
            print(f"اكتمل: أُدخل {inserted} وحُدّث {updated} كوداً — {args.system} {args.version}")


if __name__ == "__main__":
    main()
