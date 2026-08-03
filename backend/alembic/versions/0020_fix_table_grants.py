"""الهجرة 0020 — ترميم صلاحيات الجداول المُنشأة بعد 0001.

الخلل الذي عالجته: منح 0001 كان `GRANT ... ON ALL TABLES IN SCHEMA public` — وهو
يشمل الجداول الموجودة **لحظتها** فقط. قاعدة جديدة لا تُظهر المشكلة (0001 يُنشئ كل
جداول النماذج ثم يمنح)، بينما قاعدة قائمة تُرقّى بهجرات لاحقة تُنشئ جداول بلا منح
— فيرفض دور التطبيق الوصول إليها (`permission denied`). ظهر عملياً على
audio_chunks (م2) في الإنتاج.

هذه الهجرة تعيد المنح على الجداول المستحقة (idempotent، وتحترم الإلحاقية:
REVOKE يعاد تطبيقه بعد المنح على ما يجب أن يبقى إلحاقياً).

Revision ID: 0020
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

SQL = r"""
-- منح شامل على ما هو قائم الآن (يشمل كل جداول الهجرات 0002..0019)
GRANT USAGE ON SCHEMA public TO medify_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO medify_app;

-- ثم إعادة تثبيت كل REVOKE سابق حرفياً كما ورد في هجرته (الترتيب مقصود)
-- 0001
REVOKE UPDATE, DELETE ON approvals FROM medify_app;
REVOKE UPDATE, DELETE ON audit_logs FROM medify_app;
REVOKE DELETE ON visits, patients, transcripts, summaries, summary_sections, recordings FROM medify_app;
-- 0002 · 0003 · 0005 · 0006 · 0007 (المنصة والسجل المرجعي)
REVOKE ALL ON platform_admins FROM medify_app;
REVOKE ALL ON plans FROM medify_app;
REVOKE ALL ON platform_audit_logs FROM medify_app;
REVOKE ALL ON platform_settings FROM medify_app;
REVOKE INSERT, UPDATE, DELETE ON registry_codes FROM medify_app;
REVOKE INSERT, UPDATE, DELETE ON platform_default_prompts FROM medify_app;
REVOKE UPDATE ON doctor_templates FROM medify_app;
-- 0004 · 0010 (البوابتان والموافقة والنقض)
REVOKE UPDATE, DELETE ON visit_consents FROM medify_app;
REVOKE UPDATE, DELETE ON note_approvals FROM medify_app;
REVOKE UPDATE, DELETE ON note_unlocks FROM medify_app;
-- 0014 · 0015 · 0019 (التحصين)
REVOKE DELETE ON note_versions FROM medify_app;
REVOKE UPDATE, DELETE ON delivery_receipts FROM medify_app;
REVOKE UPDATE, DELETE ON metric_events FROM medify_app;
REVOKE INSERT, UPDATE, DELETE ON daily_metrics FROM medify_app;
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    # لا تراجع: إسقاط منح صحيح يكسر التطبيق بلا فائدة — الترميم آمن ودائم
    pass
