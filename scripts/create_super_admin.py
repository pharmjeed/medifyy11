"""إنشاء/تحديث حساب سوبر أدمن للإنتاج — يعمل بدور المالك (يتجاوز RLS).

الاستخدام:
    python scripts/create_super_admin.py <username> <full_name> [email]
    كلمة المرور من متغير البيئة SUPER_ADMIN_PASSWORD (إلزامي — لا تُمرر في سطر الأوامر).

إن كان الحساب موجوداً تُحدَّث كلمة مروره ويُفعَّل.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import PlatformAdmin  # noqa: E402
from app.security import hash_password  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print("الاستخدام: python scripts/create_super_admin.py <username> <full_name> [email]")
        sys.exit(1)
    username, full_name = sys.argv[1], sys.argv[2]
    email = sys.argv[3] if len(sys.argv) > 3 else None
    password = os.environ.get("SUPER_ADMIN_PASSWORD", "")
    if len(password) < 10:
        print("خطأ: اضبط SUPER_ADMIN_PASSWORD في البيئة (10 أحرف على الأقل).")
        sys.exit(1)

    settings = get_settings()
    url = os.environ.get("MIGRATIONS_DATABASE_URL") or settings.migrations_database_url or settings.database_url
    engine = create_engine(url)
    with Session(engine) as db:
        admin = db.execute(
            select(PlatformAdmin).where(PlatformAdmin.username == username)
        ).scalar_one_or_none()
        if admin is None:
            db.add(PlatformAdmin(
                username=username, full_name=full_name, email=email,
                password_hash=hash_password(password), is_active=True,
            ))
            print(f"أُنشئ السوبر أدمن: {username}")
        else:
            admin.full_name = full_name
            admin.email = email or admin.email
            admin.password_hash = hash_password(password)
            admin.is_active = True
            print(f"حُدّث السوبر أدمن: {username}")
        db.commit()


if __name__ == "__main__":
    main()
