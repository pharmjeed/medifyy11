"""الهجرة 0010 — مسار Unlock للبوابة ① (قرار مالك 2026-08-03 — حلقة CDI).

مراجعة الأكواد (②) تكشف نقص توثيق (جهة الإصابة، مع/بدون مضاعفات…) والنص مجمّد بعد ① —
بدل اعتماد كود بلا سند أو كود أقل تحديداً: نقض بسبب مسجّل → تعديل → إعادة اعتماد ① → عودة للأكواد.

- note_unlocks: نقض إلحاقي لاعتماد نص المذكرة (سبب مشفّر + الفاعل + الوقت) — قبل إتمام ② فقط.
- note_approvals.visit_id يفقد قيد UNIQUE (يبقى فهرساً): التاريخ يتراكم مع كل إعادة اعتماد،
  والحصر «نشط واحد قبل البوابة ②» يفرضه trigger (النشط = بلا صف نقض في note_unlocks).
- تجميد نص المذكرة (MDF-4226) يُعاد تعريفه: يسري مع approvals أو اعتماد ① نشط غير منقوض —
  فيسقط بالنقض ويعود بإعادة الاعتماد.
- النقض بعد البوابة ② مرفوض من القاعدة نفسها — بعد الاعتماد النهائي المسار Addendum لا Unlock.

idempotent: قاعدة جديدة تكون 0001 (create_all) أنشأت note_unlocks والفهرس — كل الأوامر شرطية.

Revision ID: 0010
"""
from alembic import op

from app.models import Base

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
-- ===== 1) UNIQUE(visit_id) → فهرس عادي: إعادة الاعتماد بعد النقض صف جديد =====
DO $$
DECLARE cname text;
BEGIN
    SELECT conname INTO cname FROM pg_constraint
    WHERE conrelid = 'note_approvals'::regclass AND contype = 'u';
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE note_approvals DROP CONSTRAINT %I', cname);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_note_approvals_visit_id ON note_approvals (visit_id);

-- ===== 2) صلاحيات note_unlocks: إلحاقي مثل note_approvals =====
GRANT SELECT, INSERT ON note_unlocks TO medify_app;
REVOKE UPDATE, DELETE ON note_unlocks FROM medify_app;

-- ===== 3) عزل المستأجر + قصر المحتوى على دكتور الزيارة (نمط note_approvals نفسه) =====
ALTER TABLE note_unlocks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON note_unlocks;
CREATE POLICY tenant_isolation ON note_unlocks FOR ALL TO medify_app
    USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
    WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);

DROP POLICY IF EXISTS doctor_scope ON note_unlocks;
CREATE POLICY doctor_scope ON note_unlocks AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor' OR EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid))
    WITH CHECK (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor' OR EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));

-- ===== 4) إلحاقية note_unlocks حتى لمالك القاعدة (forbid_mutation من 0001) =====
DROP TRIGGER IF EXISTS trg_note_unlocks_append_only ON note_unlocks;
CREATE TRIGGER trg_note_unlocks_append_only
    BEFORE UPDATE OR DELETE ON note_unlocks
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ===== 5) لا نقض بعد البوابة ② — القاعدة هي الحكم (بعد الاعتماد النهائي: Addendum) =====
-- SECURITY DEFINER ليقرأ approvals بمعزل عن سياسات RLS للجلسة الحالية.
CREATE OR REPLACE FUNCTION forbid_unlock_after_final_approval() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM approvals a WHERE a.visit_id = NEW.visit_id) THEN
        RAISE EXCEPTION 'MDF-4223: note unlock is forbidden after final approval (gate 2) - use addendum'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_note_unlocks_before_gate2 ON note_unlocks;
CREATE TRIGGER trg_note_unlocks_before_gate2
    BEFORE INSERT ON note_unlocks
    FOR EACH ROW EXECUTE FUNCTION forbid_unlock_after_final_approval();

-- ===== 6) نشط واحد لكل زيارة قبل البوابة ② =====
-- بعد ② تُنشئ بوابات الملاحق المصغّرة (0009) صفوفها بحرية — الحصر لا يسري عندها.
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

DROP TRIGGER IF EXISTS trg_note_approvals_single_active ON note_approvals;
CREATE TRIGGER trg_note_approvals_single_active
    BEFORE INSERT ON note_approvals
    FOR EACH ROW EXECUTE FUNCTION enforce_single_active_note_approval();

-- ===== 7) التجميد (MDF-4226): يسقط مع النقض ويعود مع إعادة الاعتماد =====
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
"""

# استعادة تعريف 0004 للتجميد (وجود أي note_approval يجمّد) وإرجاع UNIQUE إن أمكن
DOWNGRADE_SQL = r"""
CREATE OR REPLACE FUNCTION forbid_section_edit_after_approval() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM summaries s
        WHERE s.id = OLD.summary_id
          AND (EXISTS (SELECT 1 FROM approvals a WHERE a.visit_id = s.visit_id)
            OR EXISTS (SELECT 1 FROM note_approvals n WHERE n.visit_id = s.visit_id))
    ) THEN
        RAISE EXCEPTION 'MDF-4226: summary sections are frozen after note approval'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_note_approvals_single_active ON note_approvals;
DROP FUNCTION IF EXISTS enforce_single_active_note_approval();
DROP TRIGGER IF EXISTS trg_note_unlocks_before_gate2 ON note_unlocks;
DROP FUNCTION IF EXISTS forbid_unlock_after_final_approval();
DROP TRIGGER IF EXISTS trg_note_unlocks_append_only ON note_unlocks;
DROP TABLE IF EXISTS note_unlocks;
DROP INDEX IF EXISTS ix_note_approvals_visit_id;
ALTER TABLE note_approvals ADD CONSTRAINT note_approvals_visit_id_key UNIQUE (visit_id);
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables["note_unlocks"]],
        checkfirst=True,
    )
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
