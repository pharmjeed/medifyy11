"""الهجرة 0006 — السجل المرجعي للأكواد (قرار مالك 2026-08-02).

- registry_codes: مرجع منصّي عام للأكواد (SBS/ICD10AM/ACHI/SFDA/GMDN) بحالة نشط/ملغى
  وبديل الملغى وإصدار السجل — يُغذّى من الملفات الرسمية عبر scripts/import_codes.py.
- ليس جدولاً مستأجرياً ولا يحمل محتوى سريرياً → لا RLS (نمط plans):
  دور التطبيق SELECT فقط، والكتابة بدور المالك (الاستيراد) حصراً.

idempotent: قاعدة جديدة تكون 0001 (create_all) أنشأت الجدول — الأوامر آمنة عند الوجود.

Revision ID: 0006
"""
from alembic import op

from app.models import Base

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

GRANTS_SQL = r"""
GRANT SELECT ON registry_codes TO medify_app;
REVOKE INSERT, UPDATE, DELETE ON registry_codes FROM medify_app;
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["registry_codes"]],
        checkfirst=True,
    )
    op.execute(GRANTS_SQL)


def downgrade() -> None:
    op.drop_table("registry_codes")
