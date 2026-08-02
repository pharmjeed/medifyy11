"""الهجرة 0014 — دورة النسخ Versioned Reopen (المرحلة 6 من التحصين، الأكبر).

المبدأ 2/3 غير القابلين للتفاوض: التحرير بعد النقل = reopen → نسخة جديدة → إعادة
البوابتين → نقل بدلالة replace؛ والنسخ المنقولة لقطات immutable لا UPDATE عليها.

- «الدورة» cycle: عدّاد على visits يرتفع مع كل reopen — note_approvals/approvals
  تحمل دورتها، فتصبح triggers 0010 (نشط واحد/تجميد/حظر Unlock بعد ②) واعية بالدورة:
  ما اعتُمد في دورة سابقة لا يجمّد الدورة الجديدة، وبوابتا كل نسخة مستقلتان.
- approvals: UNIQUE(visit_id) → UNIQUE(visit_id, cycle) — اعتماد ② واحد لكل نسخة.
- upload_jobs: الربط يصير بالاعتماد مباشرة (approval_id NOT NULL UNIQUE) — أقوى من
  FK القديم إلى approvals.visit_id: كل نسخة مهمة رفع خاصة، والقاعدة تظل تمنع أي
  رفع بلا بوابة ② (FR-803).
- note_versions: لقطة كاملة لكل نسخة (نص الأقسام + الأكواد المعتمدة + bundle_hash
  + طوابع البوابتين + حالة النقل + سبب reopen + diff عن السابقة) — الصف يتجمّد
  كلياً بعد النقل (trigger) ولا يُحذف أبداً.

idempotent: كل الأوامر شرطية — قاعدة جديدة يكون 0001 (create_all) أنشأ note_versions.

Revision ID: 0014
"""
import sqlalchemy as sa
from alembic import op

from app.models import Base

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
-- ===== 1) عدّاد الدورة =====
ALTER TABLE visits ADD COLUMN IF NOT EXISTS cycle integer NOT NULL DEFAULT 1;
ALTER TABLE note_approvals ADD COLUMN IF NOT EXISTS cycle integer NOT NULL DEFAULT 1;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS cycle integer NOT NULL DEFAULT 1;

-- ===== 2) upload_jobs: من FK approvals.visit_id إلى approval_id مباشرة =====
-- مسار الترقية للقواعد القائمة فقط — قاعدة جديدة يكون create_all بنى البنية الجديدة أصلاً
DO $$
DECLARE cname text;
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'upload_jobs' AND column_name = 'approval_id') THEN
        RETURN;
    END IF;

    -- فك FK القديم (upload_jobs.visit_id → approvals.visit_id)
    SELECT conname INTO cname FROM pg_constraint
    WHERE conrelid = 'upload_jobs'::regclass AND contype = 'f'
      AND confrelid = 'approvals'::regclass;
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE upload_jobs DROP CONSTRAINT %I', cname);
    END IF;
    -- فك UNIQUE(visit_id) — مهمة رفع لكل نسخة
    SELECT conname INTO cname FROM pg_constraint
    WHERE conrelid = 'upload_jobs'::regclass AND contype = 'u'
      AND conkey = (SELECT ARRAY[attnum] FROM pg_attribute
                    WHERE attrelid = 'upload_jobs'::regclass AND attname = 'visit_id');
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE upload_jobs DROP CONSTRAINT %I', cname);
    END IF;

    EXECUTE 'ALTER TABLE upload_jobs ADD COLUMN approval_id uuid';
    EXECUTE 'UPDATE upload_jobs SET approval_id = a.id
             FROM approvals a WHERE a.visit_id = upload_jobs.visit_id';
    EXECUTE 'ALTER TABLE upload_jobs ALTER COLUMN approval_id SET NOT NULL';
    EXECUTE 'ALTER TABLE upload_jobs
             ADD CONSTRAINT fk_upload_jobs_approval FOREIGN KEY (approval_id) REFERENCES approvals (id)';
    EXECUTE 'ALTER TABLE upload_jobs ADD CONSTRAINT uq_upload_jobs_approval UNIQUE (approval_id)';
    EXECUTE 'ALTER TABLE upload_jobs
             ADD CONSTRAINT fk_upload_jobs_visit FOREIGN KEY (visit_id) REFERENCES visits (id)';
END $$;
CREATE INDEX IF NOT EXISTS ix_upload_jobs_visit_id ON upload_jobs (visit_id);

-- ===== 3) approvals: UNIQUE(visit_id) → UNIQUE(visit_id, cycle) =====
DO $$
DECLARE cname text;
BEGIN
    SELECT conname INTO cname FROM pg_constraint
    WHERE conrelid = 'approvals'::regclass AND contype = 'u'
      AND array_length(conkey, 1) = 1;
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE approvals DROP CONSTRAINT %I', cname);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'approvals'::regclass AND conname = 'uq_approvals_visit_cycle') THEN
        ALTER TABLE approvals ADD CONSTRAINT uq_approvals_visit_cycle UNIQUE (visit_id, cycle);
    END IF;
END $$;

-- ===== 4) صلاحيات note_versions + RLS (نمط note_unlocks) =====
GRANT SELECT, INSERT, UPDATE ON note_versions TO medify_app;
REVOKE DELETE ON note_versions FROM medify_app;

ALTER TABLE note_versions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON note_versions;
CREATE POLICY tenant_isolation ON note_versions FOR ALL TO medify_app
    USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
    WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);

DROP POLICY IF EXISTS doctor_scope ON note_versions;
CREATE POLICY doctor_scope ON note_versions AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor' OR EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid))
    WITH CHECK (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor' OR EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));

-- ===== 5) immutability: النسخة المنقولة لا تُمس، ولا حذف لأي نسخة أبداً =====
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

DROP TRIGGER IF EXISTS trg_note_versions_immutable ON note_versions;
CREATE TRIGGER trg_note_versions_immutable
    BEFORE UPDATE OR DELETE ON note_versions
    FOR EACH ROW EXECUTE FUNCTION forbid_uploaded_version_mutation();

-- ===== 6) triggers 0010 تصبح واعية بالدورة =====
-- لا نقض بعد ② «في الدورة نفسها» — دورة جديدة (reopen) تعيد فتح المسار لنسختها
CREATE OR REPLACE FUNCTION forbid_unlock_after_final_approval() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM approvals a
        JOIN visits v ON v.id = NEW.visit_id
        WHERE a.visit_id = NEW.visit_id AND a.cycle = v.cycle
    ) THEN
        RAISE EXCEPTION 'MDF-4236: note unlock is forbidden after final approval (gate 2) - use addendum'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- نشط واحد لكل دورة قبل بوابتها ② (بوابات الملاحق المصغّرة بعد ② خارج الحصر كما كانت)
CREATE OR REPLACE FUNCTION enforce_single_active_note_approval() RETURNS trigger AS $$
DECLARE current_cycle integer;
BEGIN
    SELECT cycle INTO current_cycle FROM visits WHERE id = NEW.visit_id;
    IF NOT EXISTS (
           SELECT 1 FROM approvals a
           WHERE a.visit_id = NEW.visit_id AND a.cycle = current_cycle
       )
       AND EXISTS (
           SELECT 1 FROM note_approvals n
           WHERE n.visit_id = NEW.visit_id AND n.cycle = current_cycle
             AND NOT EXISTS (SELECT 1 FROM note_unlocks u WHERE u.note_approval_id = n.id)
       ) THEN
        RAISE EXCEPTION 'MDF-4223: an active note approval already exists for this visit'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- التجميد يخص الدورة الحالية: reopen (دورة جديدة) يعيد فتح التحرير للنسخة الجديدة
CREATE OR REPLACE FUNCTION forbid_section_edit_after_approval() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM summaries s
        JOIN visits v ON v.id = s.visit_id
        WHERE s.id = OLD.summary_id
          AND (EXISTS (SELECT 1 FROM approvals a
                       WHERE a.visit_id = s.visit_id AND a.cycle = v.cycle)
            OR EXISTS (
                SELECT 1 FROM note_approvals n
                WHERE n.visit_id = s.visit_id AND n.cycle = v.cycle
                  AND NOT EXISTS (SELECT 1 FROM note_unlocks u WHERE u.note_approval_id = n.id)))
    ) THEN
        RAISE EXCEPTION 'MDF-4226: summary sections are frozen after note approval'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
"""

DOWNGRADE_SQL = r"""
-- إرجاع دوال 0010 (بلا وعي الدورة) وقيود ما قبل النسخ — الأعمدة تبقى (بيانات)
CREATE OR REPLACE FUNCTION forbid_unlock_after_final_approval() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM approvals a WHERE a.visit_id = NEW.visit_id) THEN
        RAISE EXCEPTION 'MDF-4223: note unlock is forbidden after final approval (gate 2) - use addendum'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION enforce_single_active_note_approval() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM approvals a WHERE a.visit_id = NEW.visit_id)
       AND EXISTS (
           SELECT 1 FROM note_approvals n
           WHERE n.visit_id = NEW.visit_id
             AND NOT EXISTS (SELECT 1 FROM note_unlocks u WHERE u.note_approval_id = n.id)
       ) THEN
        RAISE EXCEPTION 'MDF-4223: an active note approval already exists for this visit'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION forbid_section_edit_after_approval() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM summaries s
        WHERE s.id = OLD.summary_id
          AND (EXISTS (SELECT 1 FROM approvals a WHERE a.visit_id = s.visit_id)
            OR EXISTS (
                SELECT 1 FROM note_approvals n
                WHERE n.visit_id = s.visit_id
                  AND NOT EXISTS (SELECT 1 FROM note_unlocks u WHERE u.note_approval_id = n.id)))
    ) THEN
        RAISE EXCEPTION 'MDF-4226: summary sections are frozen after note approval'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_note_versions_immutable ON note_versions;
DROP FUNCTION IF EXISTS forbid_uploaded_version_mutation();
DROP TABLE IF EXISTS note_versions;
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["note_versions"]],
        checkfirst=True,
    )
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
