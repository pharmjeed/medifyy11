"""الهجرة 0007 — نظام إدارة البرومبتات متعدد المستويات (قرار مالك 2026-08-02).

- platform_default_prompts: برومبتات ديفولت من SuperAdmin (منصّي بلا RLS)
- templates: إضافة حقول prompt_content و prompt_source و prompt_template_type
- doctor_templates: ربط الدكتور بالقوالب المتاحة له (مستأجري مع RLS على facility_id)

الهيكل:
  SuperAdmin → platform_default_prompts (ديفولتات)
            ↓
  Admin المنشأة → templates (قوالب مع برومبتات)
                ↓
  عند إنشاء دكتور → doctor_templates (اختيار القوالب)
                    ↓
  الدكتور يرى فقط doctor_templates.template_id

idempotent (نمط 0004/0006): قاعدة جديدة تكون 0001 (create_all) أنشأت الأعمدة والجدولين
من النماذج — الأوامر كلها آمنة عند الوجود.

Revision ID: 0007
Requires: alembic >= 1.8
"""
from alembic import op

from app.models import Base

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ════════ 1. إضافة حقول جديدة إلى templates ════════
    op.execute("""
        ALTER TABLE templates ADD COLUMN IF NOT EXISTS prompt_content text;
        ALTER TABLE templates ADD COLUMN IF NOT EXISTS prompt_source varchar(20) NOT NULL DEFAULT 'default';
        ALTER TABLE templates ADD COLUMN IF NOT EXISTS prompt_template_type varchar(50);
    """)

    # ════════ 2+3. جدولا platform_default_prompts (SuperAdmin فقط) و doctor_templates (مستأجري) ════════
    Base.metadata.create_all(
        bind=bind,
        tables=[
            Base.metadata.tables["platform_default_prompts"],
            Base.metadata.tables["doctor_templates"],
        ],
        checkfirst=True,
    )

    # ════════ 4. إضافة سياسة RLS على doctor_templates ════════
    op.execute("""
        ALTER TABLE doctor_templates ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS doctor_templates_all ON doctor_templates;
        CREATE POLICY doctor_templates_all ON doctor_templates
            USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
            WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);
    """)

    # ════════ 5. الأذونات (GRANTS) ════════
    op.execute("""
        -- platform_default_prompts: SuperAdmin فقط (SELECT فقط للتطبيق)
        GRANT SELECT ON platform_default_prompts TO medify_app;
        REVOKE INSERT, UPDATE, DELETE ON platform_default_prompts FROM medify_app;

        -- doctor_templates: RLS يتحكم في الوصول
        GRANT SELECT, INSERT, DELETE ON doctor_templates TO medify_app;
        REVOKE UPDATE ON doctor_templates FROM medify_app;
    """)


def downgrade() -> None:
    # حذف السياسات أولاً
    op.execute("""
        DROP POLICY IF EXISTS doctor_templates_select_same_facility ON doctor_templates;
        DROP POLICY IF EXISTS doctor_templates_insert_admin ON doctor_templates;
        DROP POLICY IF EXISTS doctor_templates_delete_admin ON doctor_templates;
        ALTER TABLE doctor_templates DISABLE ROW LEVEL SECURITY;
    """)

    # حذف الجداول
    op.drop_table("doctor_templates")
    op.drop_table("platform_default_prompts")

    # حذف الأعمدة من templates
    op.drop_column("templates", "prompt_template_type")
    op.drop_column("templates", "prompt_source")
    op.drop_column("templates", "prompt_content")
