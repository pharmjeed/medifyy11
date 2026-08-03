"""الهجرة 0019 — القياس الآلي (المرحلة 15).

- metric_events: أحداث قياس بأرقام فقط (numeric_payload) — لا حقل نصي حر إطلاقاً.
  المفاتيح الوصفية (التخصص/العيادة) معرّفات وأسماء تصنيف لا محتوى سريري.
- daily_metrics: التجميع الليلي (طبيب/تخصص/عيادة) — الاستعلامات الإدارية تقرأ منه
  لا من الأحداث الخام.

idempotent: قاعدة جديدة يكون create_all بنى الجدولين من النماذج.

Revision ID: 0019
"""
from alembic import op

from app.models import Base

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
GRANT SELECT, INSERT ON metric_events TO medify_app;
REVOKE UPDATE, DELETE ON metric_events FROM medify_app;
GRANT SELECT ON daily_metrics TO medify_app;

ALTER TABLE metric_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON metric_events;
CREATE POLICY tenant_isolation ON metric_events FOR ALL TO medify_app
    USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
    WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);

ALTER TABLE daily_metrics ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON daily_metrics;
CREATE POLICY tenant_isolation ON daily_metrics FOR ALL TO medify_app
    USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
    WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["metric_events"], Base.metadata.tables["daily_metrics"]],
        checkfirst=True,
    )
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS daily_metrics; DROP TABLE IF EXISTS metric_events;")
