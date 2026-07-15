"""الهجرة 0002 — طبقة المنصة (قرار مالك 2026-07-15): السوبر أدمن والباقات.

- platform_admins: حسابات مالك ميديفاي — محجوبة كلياً عن دور التطبيق medify_app.
- plans: كتالوج الباقات (سعر المقعد لكل دورة) — قراءة فقط لدور التطبيق (الفوترة تقرأ السعر).
- subscriptions.plan يبقى نصاً ويشير تطبيقياً إلى plans.code.
- seat_events.actor_user_id يصبح NULL-able: NULL = فعل السوبر أدمن/النظام (كما audit_logs).
- بذر الباقتين الافتراضيتين monthly/yearly — الأسعار توضيحية حتى القفل (DOC-09 §٤).

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

from app.models import Base

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PLATFORM_SQL = r"""
-- ===== صلاحيات دور التطبيق على جداول المنصة =====
-- platform_admins: لا وصول إطلاقاً لدور التطبيق (تديرها مسارات السوبر أدمن بمحرك النظام)
REVOKE ALL ON platform_admins FROM medify_app;
ALTER TABLE platform_admins ENABLE ROW LEVEL SECURITY;

-- plans: كتالوج عام — قراءة فقط (الفوترة تقرأ سعر الباقة داخل جلسات RLS)
REVOKE ALL ON plans FROM medify_app;
GRANT SELECT ON plans TO medify_app;
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS plans_catalog_read ON plans;
CREATE POLICY plans_catalog_read ON plans FOR SELECT TO medify_app USING (true);

-- ===== أفعال السوبر أدمن على المقاعد: NULL = المنصة (موازٍ لـ audit_logs.actor_user_id) =====
ALTER TABLE seat_events ALTER COLUMN actor_user_id DROP NOT NULL;

-- ===== الباقتان الافتراضيتان (idempotent) =====
INSERT INTO plans (id, code, name_ar, name_en, seat_price_sar, billing_cycle, is_active, created_at, updated_at)
VALUES
    (gen_random_uuid(), 'monthly', 'شهرية', 'Monthly', 400.00, 'monthly', true, now(), now()),
    (gen_random_uuid(), 'yearly',  'سنوية', 'Yearly', 4080.00, 'yearly',  true, now(), now())
ON CONFLICT (code) DO NOTHING;
"""

DOWNGRADE_SQL = """
ALTER TABLE seat_events ALTER COLUMN actor_user_id SET NOT NULL;
DROP POLICY IF EXISTS plans_catalog_read ON plans;
"""


def upgrade() -> None:
    bind = op.get_bind()
    # checkfirst: قاعدة جديدة تكون 0001 أنشأت الجدولين ضمن metadata — لا فشل عند الوجود
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["platform_admins"], Base.metadata.tables["plans"]],
        checkfirst=True,
    )
    op.execute(PLATFORM_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
    op.drop_table("plans")
    op.drop_table("platform_admins")
    sa.Enum(name="billing_cycle").drop(op.get_bind(), checkfirst=True)
