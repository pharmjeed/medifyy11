"""الهجرة 0003 — حوكمة المنصة (DOC-20 v1.1 معتمدة 2026-07-16، المرحلة 1).

- platform_admins: role (خمس درجات) · 2FA (totp_secret_encrypted, totp_enabled, recovery_codes)
  · دورة حياة (last_login_at, invited_by, disabled_at).
- platform_audit_logs: سجل المنصة الموحّد — إلحاقي فقط (trigger)، محجوب عن medify_app.

idempotent: قاعدة جديدة تكون 0001 (create_all) أنشأت كل شيء — كل الأوامر IF NOT EXISTS.

Revision ID: 0003
"""
from alembic import op

from app.models import Base

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

GOVERNANCE_SQL = r"""
-- ===== درجات السوبر أدمن =====
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'platform_role') THEN
        CREATE TYPE platform_role AS ENUM ('owner', 'ops', 'finance', 'support', 'read_only');
    END IF;
END $$;

ALTER TABLE platform_admins ADD COLUMN IF NOT EXISTS role platform_role NOT NULL DEFAULT 'owner';
ALTER TABLE platform_admins ADD COLUMN IF NOT EXISTS totp_secret_encrypted text;
ALTER TABLE platform_admins ADD COLUMN IF NOT EXISTS totp_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE platform_admins ADD COLUMN IF NOT EXISTS recovery_codes jsonb;
ALTER TABLE platform_admins ADD COLUMN IF NOT EXISTS last_login_at timestamptz;
ALTER TABLE platform_admins ADD COLUMN IF NOT EXISTS invited_by uuid REFERENCES platform_admins(id);
ALTER TABLE platform_admins ADD COLUMN IF NOT EXISTS disabled_at timestamptz;

-- ===== سجل المنصة الموحّد: محجوب عن دور التطبيق + إلحاقي فقط =====
REVOKE ALL ON platform_audit_logs FROM medify_app;
ALTER TABLE platform_audit_logs ENABLE ROW LEVEL SECURITY;

-- إلحاقية حتى لمالك القاعدة التشغيلي — تعيد استخدام forbid_mutation() من 0001
DROP TRIGGER IF EXISTS trg_platform_audit_append_only ON platform_audit_logs;
CREATE TRIGGER trg_platform_audit_append_only
    BEFORE UPDATE OR DELETE ON platform_audit_logs
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
"""

DOWNGRADE_SQL = """
DROP TRIGGER IF EXISTS trg_platform_audit_append_only ON platform_audit_logs;
ALTER TABLE platform_admins
    DROP COLUMN IF EXISTS disabled_at,
    DROP COLUMN IF EXISTS invited_by,
    DROP COLUMN IF EXISTS last_login_at,
    DROP COLUMN IF EXISTS recovery_codes,
    DROP COLUMN IF EXISTS totp_enabled,
    DROP COLUMN IF EXISTS totp_secret_encrypted,
    DROP COLUMN IF EXISTS role;
DROP TABLE IF EXISTS platform_audit_logs;
DROP TYPE IF EXISTS platform_role;
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["platform_audit_logs"]],
        checkfirst=True,
    )
    op.execute(GOVERNANCE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
