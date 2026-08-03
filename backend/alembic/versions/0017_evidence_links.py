"""الهجرة 0017 — السند المرتبط (المرحلة 10).

summary_sections.evidence_json (نص مشفّر تطبيقياً): جملةً بجملة —
{text, segment_ids, audio_start_ms, audio_end_ms, origin} — يُبنى من P2-verify@1.1
(الذي صار يعيد الربط بدل رميه) ويُحدَّث مع كل تعديل يدوي (origin=doctor).

اختيار JSONB المضمّن لا جدول evidence_links مستقل: القراءة دائماً مع القسم،
لا استعلام عبر الزيارات، والحجم جُمَل معدودة (التبرير في PROGRESS م10).

Revision ID: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE summary_sections ADD COLUMN IF NOT EXISTS evidence_json text")


def downgrade() -> None:
    op.execute("ALTER TABLE summary_sections DROP COLUMN IF EXISTS evidence_json")
