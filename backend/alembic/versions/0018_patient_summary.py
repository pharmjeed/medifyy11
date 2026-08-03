"""الهجرة 0018 — ملخص المريض بالعربي (المرحلة 14).

يُخزَّن مع نسخته (note_versions) لأنه جزء من مخرجات النسخة: reopen → إعادة توليد
مع النسخة الجديدة، وunlock → الملخص stale حتى إعادة الاعتماد.

- patient_summary_json: {diagnosis, medications, instructions, follow_up, red_flags} مشفّر
- patient_summary_included: قرار الطبيب بالتضمين في مخارج النسخة (toggle)
- patient_summary_note_hash: بصمة نص المذكرة وقت التوليد — عدم مطابقتها = stale

Revision ID: 0018
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE note_versions ADD COLUMN IF NOT EXISTS patient_summary_json text;
        ALTER TABLE note_versions ADD COLUMN IF NOT EXISTS patient_summary_included boolean NOT NULL DEFAULT false;
        ALTER TABLE note_versions ADD COLUMN IF NOT EXISTS patient_summary_note_hash text;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE note_versions DROP COLUMN IF EXISTS patient_summary_note_hash;
        ALTER TABLE note_versions DROP COLUMN IF EXISTS patient_summary_included;
        ALTER TABLE note_versions DROP COLUMN IF EXISTS patient_summary_json;
    """)
