"""الهجرة 0012 — سجل مقاطع الصوت الخادمي (المرحلة 2 من التحصين).

القناة WS كانت تعتمد عدّاد اتصالٍ في الذاكرة (last_seq يبدأ من -1 لكل اتصال):
ضياع ack = إعادة إرسال يُلحقها الخادم ثانية = تكرار مقطع صوتي في WAV، وقتل
التبويبة يفقد موضع الاستئناف. الجدول يجعل الترقيم عالمياً معمَّراً عبر الاتصالات:
- قيد فريد (visit_id, chunk_index) — إعادة رفع نفس المقطع idempotent (re-ack بلا كتابة).
- sha256 لكل مقطع + byte_offset/byte_length — تحقق لا-فجوات وbit-exact عند finalize
  (recording/stop يرفض بـ MDF-4234 مع قائمة الناقص).

idempotent: قاعدة جديدة تكون 0001 (create_all) أنشأت الجدول من النموذج.

Revision ID: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("audio_chunks"):
        _apply_rls()
        return

    op.create_table(
        "audio_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("visit_id", sa.Uuid(), sa.ForeignKey("visits.id"), nullable=False),
        sa.Column("facility_id", sa.Uuid(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("byte_offset", sa.BigInteger(), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("visit_id", "chunk_index", name="uq_audio_chunks_visit_index"),
    )
    op.create_index("ix_audio_chunks_visit_id", "audio_chunks", ["visit_id"])
    op.create_index("ix_audio_chunks_facility_id", "audio_chunks", ["facility_id"])
    _apply_rls()


def _apply_rls() -> None:
    op.execute("""
        -- GRANT صريح: منح 0001 كان ON ALL TABLES لحظتها — الجداول اللاحقة لا يشملها
        GRANT SELECT, INSERT, UPDATE, DELETE ON audio_chunks TO medify_app;

        ALTER TABLE audio_chunks ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS tenant_isolation ON audio_chunks;
        CREATE POLICY tenant_isolation ON audio_chunks FOR ALL TO medify_app
            USING (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid)
            WITH CHECK (facility_id = NULLIF(current_setting('app.facility_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.drop_index("ix_audio_chunks_facility_id", table_name="audio_chunks")
    op.drop_index("ix_audio_chunks_visit_id", table_name="audio_chunks")
    op.drop_table("audio_chunks")
