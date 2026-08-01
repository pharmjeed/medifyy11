"""الهجرة 0005 — إعدادات المنصة (توجيه مالك 2026-08-01): اختيار نموذج الذكاء من الكونسول.

- platform_settings: مفتاح/قيمة JSONB — محجوبة كلياً عن medify_app (نمط platform_admins).
  المفتاح الأول ai.gemini_model: يتجاوز GEMINI_MODEL البيئي دون إعادة نشر.

idempotent: قاعدة جديدة تكون 0001 (create_all) أنشأت الجدول — الأوامر آمنة عند الوجود.

Revision ID: 0005
"""
from alembic import op

from app.models import Base

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SETTINGS_SQL = r"""
-- platform_settings: لا وصول إطلاقاً لدور التطبيق (تُقرأ عبر جلسة النظام فقط)
REVOKE ALL ON platform_settings FROM medify_app;
ALTER TABLE platform_settings ENABLE ROW LEVEL SECURITY;
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["platform_settings"]],
        checkfirst=True,
    )
    op.execute(SETTINGS_SQL)


def downgrade() -> None:
    op.drop_table("platform_settings")
