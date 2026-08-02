"""الهجرة 0015 — Idempotency واعٍ بالنسخة + إيصالات التسليم (المرحلة 7).

- upload_jobs.idempotency_key = "{visit_id}:{version}" بقيد فريد: الـretry يحمل
  المفتاح نفسه (لا إرسال مزدوج) والنسخة الجديدة مفتاحاً جديداً. تكامل مع ifNoneExist
  (FHIR) وMSH-10 (HL7) المبنيين في م6 — الدفاع في الطرفين.
- delivery_receipts: كل استقبال ناجح يكتب إيصاله فوراً (جلسة مستقلة)؛ وقبل أي
  إرسال يُفحص الإيصال — موجود = يُرجَع النجاح السابق بلا إرسال (انهيار بعد الإيصال
  لا يسبب إرسالاً ثانياً).

idempotent: قاعدة جديدة يكون create_all بنى البنية من النماذج.

Revision ID: 0015
"""
import sqlalchemy as sa
from alembic import op

from app.models import Base

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
-- upload_jobs.idempotency_key — مسار الترقية للقواعد القائمة
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'upload_jobs' AND column_name = 'idempotency_key') THEN
        EXECUTE 'ALTER TABLE upload_jobs ADD COLUMN idempotency_key text';
        EXECUTE 'UPDATE upload_jobs SET idempotency_key = upload_jobs.visit_id::text || '':'' || a.cycle::text
                 FROM approvals a WHERE a.id = upload_jobs.approval_id';
        EXECUTE 'ALTER TABLE upload_jobs ALTER COLUMN idempotency_key SET NOT NULL';
        EXECUTE 'ALTER TABLE upload_jobs ADD CONSTRAINT uq_upload_jobs_idempotency UNIQUE (idempotency_key)';
    END IF;
END $$;

-- صلاحيات delivery_receipts + RLS (القراءة لدور التطبيق؛ الكتابة عبر جلسة النظام)
GRANT SELECT, INSERT ON delivery_receipts TO medify_app;
REVOKE UPDATE, DELETE ON delivery_receipts FROM medify_app;

ALTER TABLE delivery_receipts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON delivery_receipts;
CREATE POLICY tenant_isolation ON delivery_receipts FOR ALL TO medify_app
    USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
    WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["delivery_receipts"]],
        checkfirst=True,
    )
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS delivery_receipts;
        ALTER TABLE upload_jobs DROP CONSTRAINT IF EXISTS uq_upload_jobs_idempotency;
        ALTER TABLE upload_jobs DROP COLUMN IF EXISTS idempotency_key;
    """)
