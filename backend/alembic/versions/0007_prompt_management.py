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

Revision ID: 0007
Requires: alembic >= 1.8
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ════════ 1. إضافة حقول جديدة إلى templates ════════
    op.add_column("templates", sa.Column(
        "prompt_content", sa.Text, nullable=True, comment="محتوى البرومبت الفعلي"
    ))
    op.add_column("templates", sa.Column(
        "prompt_source", sa.String(20), nullable=False,
        server_default="default", comment="default أو custom"
    ))
    op.add_column("templates", sa.Column(
        "prompt_template_type", sa.String(50), nullable=True,
        comment="ربط بـ platform_default_prompts (first_visit, follow_up, ...)"
    ))

    # ════════ 2. جدول platform_default_prompts (SuperAdmin فقط) ════════
    op.create_table(
        "platform_default_prompts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("template_type", sa.String(50), nullable=False, unique=False),
        sa.Column("prompt_content", sa.Text, nullable=False),
        sa.Column("version", sa.String(20), nullable=False, server_default="1.0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by"], ["platform_admins.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["platform_admins.id"]),
        sa.UniqueConstraint("template_type", "version", name="uq_platform_prompts_type_version"),
        sa.Index("ix_platform_default_prompts_template_type", "template_type"),
        sa.Index("ix_platform_default_prompts_is_active", "is_active"),
    )

    # ════════ 3. جدول doctor_templates (مستأجري) ════════
    op.create_table(
        "doctor_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["doctor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"]),
        sa.ForeignKeyConstraint(["facility_id"], ["facilities.id"]),
        sa.UniqueConstraint("doctor_id", "template_id", name="uq_doctor_templates"),
        sa.Index("ix_doctor_templates_doctor_id", "doctor_id"),
        sa.Index("ix_doctor_templates_template_id", "template_id"),
        sa.Index("ix_doctor_templates_facility_id", "facility_id"),
    )

    # ════════ 4. إضافة سياسة RLS على doctor_templates ════════
    op.execute("""
        ALTER TABLE doctor_templates ENABLE ROW LEVEL SECURITY;

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
