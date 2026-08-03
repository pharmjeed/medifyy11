"""الهجرة 0021 — مميزات الباقة (قرار مالك 2026-08-03).

يعدّل «لا باقات ميزات» (DOC-20 تعديل ٢): الاشتراك يبقى بعدد الدكاترة × تكلفة الدكتور،
ويُضاف لكل باقة **ما تُظهره للدكتور**. عمود واحد على `plans`:

    features JSONB NULL   -- {feature_key: bool} لمفاتيح app/features.py حصراً

لماذا عمود لا جدول ربط: الكتالوج في الكود (كل مفتاح مربوط بمسار تنفيذ فعلي)، فالقاعدة تحفظ
**الاختيار** لا التعريف — وجدول ربط بمفاتيح نصية بلا FK لا يضيف سلامة، ويضيف جدولاً خارج
DOC-04. NULL = افتراضات الكتالوج، فالباقات القائمة لا تفقد شيئاً بالترقية.

`plans` منصّي: دور التطبيق SELECT فقط (هجرة 0002) — القراءة تكفي للإنفاذ، والكتابة من
السوبر أدمن بجلسة النظام.

**ترميم عرضي لازم**: الهجرة 0020 أعادت `REVOKE ALL ON plans FROM medify_app` دون إعادة
`GRANT SELECT` الذي منحته 0002 — فقاعدةٌ رُقّيت إلى 0020 تمنع دور التطبيق من قراءة `plans`
(يظهر في `billing.plan_seat_price` كـ permission denied لا كاحتياطي). حسم المميزات يقرأ
الجدول من جلسة الدكتور، فالمنح يعود هنا صراحةً.

idempotent: قاعدة جديدة تكون 0001 (create_all) أنشأت العمود — `IF NOT EXISTS` يغطي الحالتين.

Revision ID: 0021
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

SQL = r"""
ALTER TABLE plans ADD COLUMN IF NOT EXISTS features JSONB;

-- تأكيد وضع القراءة لدور التطبيق (نمط 0002/0020): يقرأ الباقة ليحسم المميزات، ولا يكتبها
GRANT SELECT ON plans TO medify_app;
REVOKE INSERT, UPDATE, DELETE ON plans FROM medify_app;
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS features;")
