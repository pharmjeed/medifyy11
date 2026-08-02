"""الهجرة 0009 — مسار الملاحق Addendum بعد الاعتماد النهائي (قرار مالك 2026-08-03 — CBAHI).

- جدول `addendums` يحمل ملحقاً على مذكرة معتمدة: نص جديد مرتبط بالزيارة الأصلية،
  له طابعه الزمني (created_at) ومُضيفه (created_by).
- الملحق يمر بوابة ① مصغّرة (note_approval_id) ويحتمل بوابة ② مصغّرة (approval_id) إن احتوى أكواداً.
- محتوى الملحق مشفّر (EncryptedJSON): {sections: [{section_key, content}]}.
- is_approved: هل موافق عليه من قِبل الدكتور (بوابة ① مصغّرة).
- عند التصدير (PDF/FHIR): الأصل + الملاحق بالترتيب الزمني.

Revision ID: 0009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # إنشاء جدول addendums
    op.create_table(
        "addendums",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("visit_id", postgresql.UUID(), nullable=False),
        sa.Column("facility_id", postgresql.UUID(), nullable=False),
        sa.Column("created_by", postgresql.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("note_approval_id", postgresql.UUID(), nullable=True),
        sa.Column("approval_id", postgresql.UUID(), nullable=True),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], name="fk_addendums_visit_id"),
        sa.ForeignKeyConstraint(["facility_id"], ["facilities.id"], name="fk_addendums_facility_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_addendums_created_by"),
        sa.ForeignKeyConstraint(["note_approval_id"], ["note_approvals.id"], name="fk_addendums_note_approval"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], name="fk_addendums_approval"),
        sa.PrimaryKeyConstraint("id", name="pk_addendums"),
    )

    # Indexes للأداء
    op.create_index("ix_addendums_visit_id", "addendums", ["visit_id"])
    op.create_index("ix_addendums_facility_id", "addendums", ["facility_id"])
    op.create_index("ix_addendums_created_by", "addendums", ["created_by"])

    # RLS: أسطر الملاحق محمية مثل أي محتوى سريري
    op.execute("""
        ALTER TABLE addendums ENABLE ROW LEVEL SECURITY;

        CREATE POLICY addendums_facility_isolation ON addendums
            USING (facility_id = current_setting('app.facility_id')::uuid OR current_setting('app.scope') = 'platform')
            WITH CHECK (facility_id = current_setting('app.facility_id')::uuid OR current_setting('app.scope') = 'platform');
    """)


def downgrade() -> None:
    op.drop_table("addendums")
