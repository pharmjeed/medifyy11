"""الهجرة 0004 — موافقة المريض + بوابتا الاعتماد + هيكلة بنود الخطة (توجيه المالك 2026-07-22).

- visit_consents: موافقة موثّقة إلحاقية · trigger يمنع draft→recording بلا موافقة (MDF-4230).
- note_approvals: بوابة ① (نص المذكرة) · approvals.note_approval_id NOT NULL يفرض ①→② بمفتاح أجنبي.
- guidance_items: كود ثانوي (GTIN/SBS) · إصدار السجل المرجعي وتاريخ سريانه · درجة ثقة ·
  requires_doctor_input · linked_dx_code (ICD-10-AM) · justification (إلزامي للجهاز بـCHECK).
- guidance_kind: + clinical_service + clinical_device.

idempotent: قاعدة جديدة تكون 0001 (create_all) أنشأت كل شيء — كل الأوامر IF NOT EXISTS.

Revision ID: 0004
"""
from alembic import op

from app.models import Base

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# ملاحظة: ADD VALUE يُنفَّذ أولاً وبمعزل عن أي استخدام للقيمة الجديدة في نفس المعاملة،
# ولذلك يستعمل CHECK لاحقاً kind::text لا مقارنة enum مباشرة.
ENUM_SQL = r"""
ALTER TYPE guidance_kind ADD VALUE IF NOT EXISTS 'clinical_service';
ALTER TYPE guidance_kind ADD VALUE IF NOT EXISTS 'clinical_device';
"""

UPGRADE_SQL = r"""
-- ===== 1) بنود الخطة: كيان مهيكل بكوده + provenance + ثقة =====
ALTER TABLE guidance_items ADD COLUMN IF NOT EXISTS code_secondary_system text;
ALTER TABLE guidance_items ADD COLUMN IF NOT EXISTS code_secondary_value text;
ALTER TABLE guidance_items ADD COLUMN IF NOT EXISTS code_registry_version text;
ALTER TABLE guidance_items ADD COLUMN IF NOT EXISTS code_effective_date text;
ALTER TABLE guidance_items ADD COLUMN IF NOT EXISTS confidence double precision;
ALTER TABLE guidance_items ADD COLUMN IF NOT EXISTS requires_doctor_input boolean NOT NULL DEFAULT false;
ALTER TABLE guidance_items ADD COLUMN IF NOT EXISTS linked_dx_code text;
ALTER TABLE guidance_items ADD COLUMN IF NOT EXISTS justification text;

-- الجهاز بلا مبرر مرفوض على مستوى القاعدة (توجيه المالك: «بحقل مبرر إلزامي»)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_guidance_device_justification'
    ) THEN
        ALTER TABLE guidance_items ADD CONSTRAINT ck_guidance_device_justification
            CHECK (kind::text <> 'clinical_device' OR justification IS NOT NULL);
    END IF;
END $$;

-- ===== 2) بوابة ① ثم ② — الترتيب مفروض بمفتاح أجنبي =====
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS note_approval_id uuid;

-- ترحيل الاعتمادات القائمة: لكل approval سابق تُشتق بوابة ① بنفس بصمة النص ووقت الاعتماد
INSERT INTO note_approvals (id, visit_id, facility_id, approved_by, approved_at, summary_hash,
                            created_at, updated_at)
SELECT gen_random_uuid(), a.visit_id, a.facility_id, a.approved_by, a.approved_at, a.summary_hash,
       a.created_at, a.updated_at
FROM approvals a
WHERE a.note_approval_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM note_approvals n WHERE n.visit_id = a.visit_id);

UPDATE approvals a
SET note_approval_id = n.id
FROM note_approvals n
WHERE n.visit_id = a.visit_id AND a.note_approval_id IS NULL;

-- قاعدة جديدة: create_all أنشأ المفتاح باسم مولَّد — لا نضيف مفتاحاً مكرراً
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'approvals'::regclass
          AND contype = 'f'
          AND confrelid = 'note_approvals'::regclass
    ) THEN
        ALTER TABLE approvals ADD CONSTRAINT fk_approvals_note_approval
            FOREIGN KEY (note_approval_id) REFERENCES note_approvals(id);
    END IF;
END $$;

ALTER TABLE approvals ALTER COLUMN note_approval_id SET NOT NULL;

-- ===== 3) صلاحيات الجدولين الجديدين: إلحاقية مثل approvals =====
GRANT SELECT, INSERT ON visit_consents, note_approvals TO medify_app;
REVOKE UPDATE, DELETE ON visit_consents FROM medify_app;
REVOKE UPDATE, DELETE ON note_approvals FROM medify_app;

-- ===== 4) عزل المستأجر + قصر المحتوى على دكتور الزيارة =====
ALTER TABLE visit_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE note_approvals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON visit_consents;
CREATE POLICY tenant_isolation ON visit_consents FOR ALL TO medify_app
    USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
    WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);

DROP POLICY IF EXISTS tenant_isolation ON note_approvals;
CREATE POLICY tenant_isolation ON note_approvals FOR ALL TO medify_app
    USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
    WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);

-- نفس نمط doctor_scope على approvals: الدكتور لزياراته، والأدمن يمر (بلا محتوى سريري)
DROP POLICY IF EXISTS doctor_scope ON visit_consents;
CREATE POLICY doctor_scope ON visit_consents AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor' OR EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid))
    WITH CHECK (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor' OR EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));

DROP POLICY IF EXISTS doctor_scope ON note_approvals;
CREATE POLICY doctor_scope ON note_approvals AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor' OR EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid))
    WITH CHECK (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor' OR EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));

-- ===== 5) إلحاقية الجدولين حتى لمالك القاعدة (تعيد استخدام forbid_mutation من 0001) =====
DROP TRIGGER IF EXISTS trg_visit_consents_append_only ON visit_consents;
CREATE TRIGGER trg_visit_consents_append_only
    BEFORE UPDATE OR DELETE ON visit_consents
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

DROP TRIGGER IF EXISTS trg_note_approvals_append_only ON note_approvals;
CREATE TRIGGER trg_note_approvals_append_only
    BEFORE UPDATE OR DELETE ON note_approvals
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ===== 6) تجميد نص المذكرة يبدأ من البوابة ① لا ② (بصمة ① يجب أن تبقى صادقة) =====
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

-- ===== 7) المنع التقني: لا تسجيل قبل موافقة موثّقة (MDF-4230) =====
-- SECURITY DEFINER ليقرأ الموافقة بمعزل عن سياسات RLS للجلسة الحالية.
-- يُطبَّق على المسار المشروع فقط (draft→recording)؛ الانتقالات الأخرى تتركها
-- لآلة الحالات (MDF-4223) حتى لا يحجب هذا الحارس رسالة الحالة الصحيحة.
CREATE OR REPLACE FUNCTION enforce_consent_before_recording() RETURNS trigger AS $$
BEGIN
    IF NEW.state = 'recording' AND OLD.state = 'draft' THEN
        IF NOT EXISTS (SELECT 1 FROM visit_consents c WHERE c.visit_id = NEW.id) THEN
            RAISE EXCEPTION 'MDF-4230: patient consent required before recording'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_consent_before_recording ON visits;
CREATE TRIGGER trg_consent_before_recording
    BEFORE UPDATE OF state ON visits
    FOR EACH ROW EXECUTE FUNCTION enforce_consent_before_recording();
"""

DOWNGRADE_SQL = """
DROP TRIGGER IF EXISTS trg_consent_before_recording ON visits;
DROP FUNCTION IF EXISTS enforce_consent_before_recording();
DROP TRIGGER IF EXISTS trg_note_approvals_append_only ON note_approvals;
DROP TRIGGER IF EXISTS trg_visit_consents_append_only ON visit_consents;
ALTER TABLE approvals DROP CONSTRAINT IF EXISTS fk_approvals_note_approval;
ALTER TABLE approvals DROP COLUMN IF EXISTS note_approval_id;
ALTER TABLE guidance_items DROP CONSTRAINT IF EXISTS ck_guidance_device_justification;
ALTER TABLE guidance_items
    DROP COLUMN IF EXISTS justification,
    DROP COLUMN IF EXISTS linked_dx_code,
    DROP COLUMN IF EXISTS requires_doctor_input,
    DROP COLUMN IF EXISTS confidence,
    DROP COLUMN IF EXISTS code_effective_date,
    DROP COLUMN IF EXISTS code_registry_version,
    DROP COLUMN IF EXISTS code_secondary_value,
    DROP COLUMN IF EXISTS code_secondary_system;
DROP TABLE IF EXISTS note_approvals;
DROP TABLE IF EXISTS visit_consents;
DROP TYPE IF EXISTS consent_method;
"""


def upgrade() -> None:
    bind = op.get_bind()
    # قيم enum الجديدة تُضاف بمعاملة مستقلة قبل أي استخدام لها
    with op.get_context().autocommit_block():
        op.execute(ENUM_SQL)
    Base.metadata.create_all(
        bind=bind,
        tables=[
            Base.metadata.tables["visit_consents"],
            Base.metadata.tables["note_approvals"],
        ],
        checkfirst=True,
    )
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
