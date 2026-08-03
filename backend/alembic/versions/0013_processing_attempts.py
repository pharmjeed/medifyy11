"""الهجرة 0013 — سجل محاولات المعالجة (المرحلة 3 من التحصين).

محاولات P1/P2/P3 كانت بالذاكرة فقط (backoff بلا أثر): الجدول يوثّق كل محاولة
(المرحلة، الرقم، تصنيف الخطأ، التفصيل بلا PHI، الأزمنة) — يُكتب بجلسة نظام مستقلة
لينجو من rollback الطلب الفاشل، فيبقى سجل الفشل النهائي (MDF-5031/5032) كاملاً.

idempotent: قاعدة جديدة تكون 0001 (create_all) أنشأت الجدول من النموذج.

Revision ID: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("processing_attempts"):
        _apply_rls()
        return

    op.create_table(
        "processing_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("visit_id", sa.Uuid(), sa.ForeignKey("visits.id"), nullable=False),
        sa.Column("facility_id", sa.Uuid(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),  # P1 | P2 | P3
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("error_class", sa.Text(), nullable=False),  # retryable | non_retryable | none
        sa.Column("error_detail", sa.Text(), nullable=True),  # صنف الاستثناء + مقتطع رسالة — بلا PHI
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_processing_attempts_visit_id", "processing_attempts", ["visit_id"])
    op.create_index("ix_processing_attempts_facility_id", "processing_attempts", ["facility_id"])
    _apply_rls()


def _apply_rls() -> None:
    op.execute("""
        -- GRANT صريح (انظر 0012): منح 0001 لا يشمل الجداول المُنشأة لاحقاً
        GRANT SELECT, INSERT, UPDATE, DELETE ON processing_attempts TO medify_app;

        ALTER TABLE processing_attempts ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS tenant_isolation ON processing_attempts;
        CREATE POLICY tenant_isolation ON processing_attempts FOR ALL TO medify_app
            USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
            WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.drop_index("ix_processing_attempts_facility_id", table_name="processing_attempts")
    op.drop_index("ix_processing_attempts_visit_id", table_name="processing_attempts")
    op.drop_table("processing_attempts")
