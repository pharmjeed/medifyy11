"""الهجرة 0008 — مسار الإبطال Void من in_review (قرار مالك 2026-08-03).

- قيمة جديدة voided في visit_state: حالة نهائية تُميَّز عن cancelled —
  الإلغاء قبل وجود محتوى (draft/recording)، والإبطال بعد اكتمال المعالجة (in_review)
  لزيارة لا يصح اعتمادها (مريض خطأ / مكررة / تجريبية / سحب موافقة).
- استبدال دالة آلة الحالات للسماح بـ in_review → voided فقط؛ voided نهائية —
  لا اعتماد ولا رفع بعدها (يظل الحكم النهائي للقاعدة لا للتطبيق).
- Void ≠ Delete: سجل الإبطال (الفاعل/السبب/الوقت) في audit_logs الإلحاقي،
  والمحتوى السريري يبقى مقفولاً خارج المخارج والإحصائيات.

idempotent: قاعدة جديدة تكون 0001 (create_all) أنشأت النوع بقيمة voided —
ADD VALUE IF NOT EXISTS آمنة عندها، والدالة تُستبدل بلا شرط.

Revision ID: 0008
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# الخريطة الكاملة كما في 0001 + السطر الجديد in_review → voided
STATE_MACHINE_WITH_VOID = r"""
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

STATE_MACHINE_WITHOUT_VOID = r"""
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
"""


def upgrade() -> None:
    # ADD VALUE داخل معاملة مسموح (PG 12+) ما دامت القيمة لا تُستخدم في المعاملة نفسها —
    # ونحن لا نستخدمها هنا (نص الدالة لا يُقيَّم). autocommit احتياط لعنقود أقدم.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE visit_state ADD VALUE IF NOT EXISTS 'voided'")
    op.execute(STATE_MACHINE_WITH_VOID)


def downgrade() -> None:
    # قيمة enum لا تُحذف في PostgreSQL — يُعاد تضييق آلة الحالات فقط فتصبح voided معزولة
    op.execute(STATE_MACHINE_WITHOUT_VOID)
