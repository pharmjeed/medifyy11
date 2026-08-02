"""الهجرة 0016 — سياسة الاحتفاظ الموحّدة (المرحلة 8).

- retention_policies: تجاوزات لكل منشأة فوق الافتراضات المضمّنة (audio=90 ·
  transcript_raw=90 · intermediate_drafts=30 · ai_chat_logs=90 ·
  note_versions_uploaded=365 · audit_log=3650 · aggregated_metrics=بلا حذف).
- visits.legal_hold: تجميد كل حذف لأثار الزيارة.
- transcripts.deleted_at: مرحلة soft قبل الحذف الصلب (سماح 7 أيام).
- صمام الحذف الاحتفاظي: triggers الإلحاقية تسمح بـ DELETE فقط عندما تضبط مهمة
  الاحتفاظ (بدور المالك) العلم medify.retention='purge' — دور التطبيق محجوب
  أصلاً بـ REVOKE DELETE فلا يتغير شيء في وجهه.

idempotent: قاعدة جديدة يكون create_all بنى الجداول/الأعمدة من النماذج.

Revision ID: 0016
"""
import sqlalchemy as sa
from alembic import op

from app.models import Base

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
ALTER TABLE visits ADD COLUMN IF NOT EXISTS legal_hold boolean NOT NULL DEFAULT false;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

-- صلاحيات retention_policies + RLS — الأدمن يعدّل سياسات منشأته (الحارس التطبيقي للدور)
GRANT SELECT, INSERT, UPDATE, DELETE ON retention_policies TO medify_app;

ALTER TABLE retention_policies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON retention_policies;
CREATE POLICY tenant_isolation ON retention_policies FOR ALL TO medify_app
    USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
    WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);

-- صمام الاحتفاظ في forbid_mutation المشترك: DELETE على audit_logs فقط وبالعلم فقط —
-- UPDATE يبقى محظوراً دائماً وعلى كل الجداول الإلحاقية الأخرى لا يتغير شيء
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND TG_TABLE_NAME = 'audit_logs'
       AND NULLIF(current_setting('medify.retention', true), '') = 'purge' THEN
        RETURN OLD;  -- حذف احتفاظي مجدول (audit_log=3650 يوماً افتراضاً) — المرحلة 8
    END IF;
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

-- صمام الاحتفاظ لنسخ المذكرة المنقولة: DELETE بالعلم فقط؛ UPDATE بعد النقل محظور دائماً
CREATE OR REPLACE FUNCTION forbid_uploaded_version_mutation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF NULLIF(current_setting('medify.retention', true), '') = 'purge' THEN
            RETURN OLD;  -- انقضت مدة note_versions_uploaded — المرحلة 8
        END IF;
        RAISE EXCEPTION 'note_versions are append-only - versions are never deleted'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.upload_status = 'uploaded' THEN
        RAISE EXCEPTION 'uploaded note version is immutable - reopen creates a new version'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DOWNGRADE_SQL = r"""
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION forbid_uploaded_version_mutation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'note_versions are append-only - versions are never deleted'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.upload_status = 'uploaded' THEN
        RAISE EXCEPTION 'uploaded note version is immutable - reopen creates a new version'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TABLE IF EXISTS retention_policies;
ALTER TABLE transcripts DROP COLUMN IF EXISTS deleted_at;
ALTER TABLE visits DROP COLUMN IF EXISTS legal_hold;
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["retention_policies"]],
        checkfirst=True,
    )
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
