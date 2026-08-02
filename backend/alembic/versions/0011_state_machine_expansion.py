"""الهجرة 0011 — توسعة آلة الحالات (المرحلة 1 من التحصين الشامل).

- قيمة جديدة reopened: فتح زيارة منقولة لإنشاء نسخة جديدة ببوابتين (دورة النسخ — المرحلة 6).
  المسار الشرعي الوحيد للتعديل بعد النقل: uploaded → reopened → in_review.
- توسعة مصادر voided (مواصفة الإبطال — المرحلة 4): summarized وapproved قبل النقل،
  إضافة إلى in_review القائمة (0008). خريطة أسماء التوجيه: note_approved = in_review
  والبوابة ① نشطة · codes_approved = approved قبل الرفع — كلاهما داخل المصدرين هنا.
  من uploaded وما بعدها الإبطال مرفوض — المسار reopen. upload_failed ليست مصدر إبطال
  (المواصفة تحصر المصادر الأربعة) — مسارها retry-upload ثم reopen عند الحاجة.

idempotent: ADD VALUE IF NOT EXISTS، والدالة تُستبدل بلا شرط.

Revision ID: 0011
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# الخريطة الكاملة — 0008 + مصادر voided الموسعة + دورة reopen
STATE_MACHINE_V0011 = r"""
CREATE OR REPLACE FUNCTION enforce_visit_state_machine() RETURNS trigger AS $$
BEGIN
    IF OLD.state = NEW.state THEN
        RETURN NEW;
    END IF;
    IF NOT (
        (OLD.state = 'draft'         AND NEW.state IN ('recording', 'cancelled')) OR
        (OLD.state = 'recording'     AND NEW.state IN ('transcribed', 'cancelled')) OR
        (OLD.state = 'transcribed'   AND NEW.state = 'summarized') OR
        (OLD.state = 'summarized'    AND NEW.state IN ('in_review', 'voided')) OR
        (OLD.state = 'in_review'     AND NEW.state IN ('approved', 'voided')) OR
        (OLD.state = 'approved'      AND NEW.state IN ('uploaded', 'upload_failed', 'voided')) OR
        (OLD.state = 'upload_failed' AND NEW.state = 'uploaded') OR
        (OLD.state = 'uploaded'      AND NEW.state = 'reopened') OR
        (OLD.state = 'reopened'      AND NEW.state = 'in_review')
    ) THEN
        RAISE EXCEPTION 'MDF-4223: visit state transition % -> % not allowed', OLD.state, NEW.state
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# خريطة 0008 كما كانت — للتراجع (قيمة enum لا تُحذف في PostgreSQL فتبقى reopened معزولة)
STATE_MACHINE_V0008 = r"""
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
        (OLD.state = 'in_review'     AND NEW.state IN ('approved', 'voided')) OR
        (OLD.state = 'approved'      AND NEW.state IN ('uploaded', 'upload_failed')) OR
        (OLD.state = 'upload_failed' AND NEW.state = 'uploaded')
    ) THEN
        RAISE EXCEPTION 'MDF-4223: visit state transition % -> % not allowed', OLD.state, NEW.state
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE visit_state ADD VALUE IF NOT EXISTS 'reopened'")
    op.execute(STATE_MACHINE_V0011)


def downgrade() -> None:
    op.execute(STATE_MACHINE_V0008)
