"""الهجرة 0001 — كل جداول DOC-04 v1.1 + RLS + triggers + صلاحيات medify_app.

القيود الإلزامية (DOC-04 §٧ / CLAUDE-CODE-PROMPT §٣):
- RLS على كل جدول مستأجري عبر current_setting('app.facility_id').
- فلتر الدكتور RESTRICTIVE + حجب المحتوى السريري عن الأدمن (DOC-06).
- آلة حالات visits عبر trigger (MDF-4223) و cancelled من draft/recording فقط.
- approvals و audit_logs إلحاقية فقط (REVOKE + trigger).
- upload_jobs.visit_id → FK إلى approvals.visit_id (لا رفع بلا اعتماد — FR-803).
- منع تعديل summary_sections بعد الاعتماد (MDF-4226).
- CHECK يمنع تعطيل ICD10AM.

Revision ID: 0001
"""
from alembic import op

from app.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# الجداول المستأجرة المباشرة (تحمل facility_id)
TENANT_TABLES = [
    "users", "clinics", "subscriptions", "invoices", "integration_configs",
    "coding_system_configs", "patients", "patient_context_snapshots", "templates",
    "visits", "recordings", "transcripts", "summaries", "summary_sections",
    "guidance_items", "edit_events", "approvals", "upload_jobs",
    "audit_logs", "notifications",
]

RLS_SQL = r"""
-- ===== دور التطبيق (خاضع لـ RLS — يُنشأ إن غاب؛ كلمة المرور تُضبط خارج الهجرة) =====
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'medify_app') THEN
        CREATE ROLE medify_app NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO medify_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO medify_app;
-- الإلحاقية: approvals و audit_logs — INSERT/SELECT فقط (DOC-04 §٧)
REVOKE UPDATE, DELETE ON approvals FROM medify_app;
REVOKE UPDATE, DELETE ON audit_logs FROM medify_app;
-- لا حذف للزيارات ولا للمرضى من التطبيق (الإلغاء حالة، والمرضى مزامنة)
REVOKE DELETE ON visits, patients, transcripts, summaries, summary_sections, recordings FROM medify_app;

-- ===== سياسة العزل الأساسية على كل جدول يحمل facility_id =====
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users','clinics','subscriptions','invoices','integration_configs',
        'coding_system_configs','patients','patient_context_snapshots','templates',
        'visits','recordings','transcripts','summaries','summary_sections',
        'guidance_items','edit_events','approvals','upload_jobs','audit_logs','notifications'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I FOR ALL TO medify_app
             USING (facility_id = NULLIF(current_setting(''app.facility_id'', true), '''')::uuid)
             WITH CHECK (facility_id = NULLIF(current_setting(''app.facility_id'', true), '''')::uuid)', t);
    END LOOP;
END $$;

-- facilities (جذر الاستئجار — العزل على id نفسه)
ALTER TABLE facilities ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON facilities FOR ALL TO medify_app
    USING (id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
    WITH CHECK (id = NULLIF(current_setting('app.facility_id', true), '')::uuid);

-- seat_events (بلا facility_id — D-18: العزل عبر الاشتراك)
ALTER TABLE seat_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON seat_events FOR ALL TO medify_app
    USING (EXISTS (SELECT 1 FROM subscriptions s WHERE s.id = subscription_id
                   AND s.facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid))
    WITH CHECK (EXISTS (SELECT 1 FROM subscriptions s WHERE s.id = subscription_id
                        AND s.facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid));

-- upload_attempts (العزل عبر المهمة)
ALTER TABLE upload_attempts ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON upload_attempts FOR ALL TO medify_app
    USING (EXISTS (SELECT 1 FROM upload_jobs j WHERE j.id = job_id
                   AND j.facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid))
    WITH CHECK (EXISTS (SELECT 1 FROM upload_jobs j WHERE j.id = job_id
                        AND j.facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid));

-- password_reset_tokens (العزل عبر المستخدم؛ الإصدار/الصرف عبر المسار النظامي)
ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON password_reset_tokens FOR ALL TO medify_app
    USING (EXISTS (SELECT 1 FROM users u WHERE u.id = user_id
                   AND u.facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid));

-- ===== فلتر الدكتور + حجب المحتوى السريري عن الأدمن (DOC-06) — سياسات تقييدية =====
-- الزيارات: الدكتور يرى زياراته فقط؛ الأدمن يمر (صفوف بلا محتوى سريري — للوحات/الرفع)
CREATE POLICY doctor_scope ON visits AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor'
           OR doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor'
                OR doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

-- المحتوى السريري: للدكتور صاحب الزيارة حصراً — الأدمن محجوب كلياً
CREATE POLICY clinical_doctor_only ON recordings AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) = 'doctor' AND EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));
CREATE POLICY clinical_doctor_only ON transcripts AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) = 'doctor' AND EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));
CREATE POLICY clinical_doctor_only ON summaries AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) = 'doctor' AND EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));
CREATE POLICY clinical_doctor_only ON summary_sections AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) = 'doctor' AND EXISTS (
        SELECT 1 FROM summaries s JOIN visits v ON v.id = s.visit_id
        WHERE s.id = summary_id AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));
CREATE POLICY clinical_doctor_only ON guidance_items AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) = 'doctor' AND EXISTS (
        SELECT 1 FROM summary_sections sec JOIN summaries s ON s.id = sec.summary_id
        JOIN visits v ON v.id = s.visit_id
        WHERE sec.id = section_id AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));
CREATE POLICY clinical_doctor_only ON edit_events AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) = 'doctor' AND EXISTS (
        SELECT 1 FROM visits v WHERE v.id = visit_id
        AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));
CREATE POLICY clinical_doctor_only ON patient_context_snapshots AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) = 'doctor');

-- المرضى: بحث/قراءة للدكتور فقط داخل منشأته (DOC-06 §٣ — الأدمن ✗)
CREATE POLICY patients_doctor_only ON patients AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) = 'doctor');

-- الاعتماد: الدكتور صاحب الزيارة حصراً (الأدمن يمر للبيانات الوصفية في لوحاته)
CREATE POLICY doctor_scope ON approvals AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor'
           OR approved_by = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor'
                OR approved_by = NULLIF(current_setting('app.user_id', true), '')::uuid);

-- مهام الرفع: بيانات وصفية — الدكتور لزياراته، الأدمن يمر (W-209)
CREATE POLICY doctor_scope ON upload_jobs AS RESTRICTIVE FOR ALL TO medify_app
    USING (current_setting('app.user_role', true) IS DISTINCT FROM 'doctor'
           OR EXISTS (SELECT 1 FROM visits v WHERE v.id = visit_id
                      AND v.doctor_id = NULLIF(current_setting('app.user_id', true), '')::uuid));

-- القوالب: الأدمن يدير العامة فقط؛ الدكتور: العامة + شخصياته (DOC-06 §٣)
CREATE POLICY template_scope ON templates AS RESTRICTIVE FOR ALL TO medify_app
    USING (
        (current_setting('app.user_role', true) = 'admin' AND owner_user_id IS NULL)
        OR (current_setting('app.user_role', true) = 'doctor'
            AND (owner_user_id IS NULL OR owner_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid))
    )
    WITH CHECK (
        (current_setting('app.user_role', true) = 'admin' AND owner_user_id IS NULL)
        OR (current_setting('app.user_role', true) = 'doctor'
            AND (owner_user_id IS NULL OR owner_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid))
    );

-- الإشعارات: كلٌّ يقرأ/يحدّث إشعاراته فقط (الإنشاء لأي مستخدم داخل المنشأة — النظام يُشعِر الآخرين)
CREATE POLICY own_notifications_select ON notifications AS RESTRICTIVE FOR SELECT TO medify_app
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY own_notifications_update ON notifications AS RESTRICTIVE FOR UPDATE TO medify_app
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);

-- ===== آلة حالات الزيارة (DOC-04 §٥ + قرار مالك 2026-07-14) =====
CREATE OR REPLACE FUNCTION enforce_visit_state_machine() RETURNS trigger AS $$
BEGIN
    IF OLD.state = NEW.state THEN
        RETURN NEW;
    END IF;
    IF NOT (
        (OLD.state = 'draft'         AND NEW.state IN ('recording', 'cancelled')) OR
        (OLD.state = 'recording'     AND NEW.state IN ('transcribed', 'cancelled')) OR
        (OLD.state = 'transcribed'   AND NEW.state = 'summarized') OR
        (OLD.state = 'summarized'    AND NEW.state = 'in_review') OR
        (OLD.state = 'in_review'     AND NEW.state = 'approved') OR
        (OLD.state = 'approved'      AND NEW.state IN ('uploaded', 'upload_failed')) OR
        (OLD.state = 'upload_failed' AND NEW.state = 'uploaded')
    ) THEN
        RAISE EXCEPTION 'MDF-4223: visit state transition % -> % not allowed', OLD.state, NEW.state
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_visit_state_machine
    BEFORE UPDATE OF state ON visits
    FOR EACH ROW EXECUTE FUNCTION enforce_visit_state_machine();

-- ===== الإلحاقية: approvals و audit_logs — حتى لمالك القاعدة التشغيلي =====
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % on % is forbidden (NFR-10)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_approvals_append_only
    BEFORE UPDATE OR DELETE ON approvals
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER trg_audit_logs_append_only
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ===== منع تعديل أقسام الملخص بعد الاعتماد (MDF-4226) =====
CREATE OR REPLACE FUNCTION forbid_section_edit_after_approval() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM approvals a
        JOIN summaries s ON s.visit_id = a.visit_id
        WHERE s.id = OLD.summary_id
    ) THEN
        RAISE EXCEPTION 'MDF-4226: summary sections are frozen after approval'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sections_frozen_after_approval
    BEFORE UPDATE ON summary_sections
    FOR EACH ROW EXECUTE FUNCTION forbid_section_edit_after_approval();
"""

DOWNGRADE_SQL = """
DROP TRIGGER IF EXISTS trg_sections_frozen_after_approval ON summary_sections;
DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs;
DROP TRIGGER IF EXISTS trg_approvals_append_only ON approvals;
DROP TRIGGER IF EXISTS trg_visit_state_machine ON visits;
DROP FUNCTION IF EXISTS forbid_section_edit_after_approval();
DROP FUNCTION IF EXISTS forbid_mutation();
DROP FUNCTION IF EXISTS enforce_visit_state_machine();
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.execute(RLS_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
    Base.metadata.drop_all(bind=op.get_bind())
