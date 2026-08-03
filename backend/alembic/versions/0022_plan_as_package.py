"""الهجرة 0022 — الباقة نوع منتج بسعرين، لا دورة فوترة (قرار مالك 2026-08-03).

قبلها: صف `plans` = **دورة** («شهرية» 400 · «سنوية» 4080)، و`subscriptions.plan` يحمل الدورة.
بعدها: صف `plans` = **باقة** لها سعر شهري وسعر سنوي وخريطة مميزات واحدة، والدورة انتقلت
إلى `subscriptions.billing_cycle`.

لماذا صف واحد بسعرين لا صف لكل (باقة × دورة): خريطة المميزات (هجرة 0021) لا تتفرّق —
باقة بصفّين تعني أن تفعيل ميزة في «احترافية-شهري» ونسيانها في «احترافية-سنوي» خطأ صامت
يظهر عند العميل. سعر NULL = الباقة لا تُباع بتلك الدورة، وقيد CHECK يمنع باقة بلا سعر.

### ترحيل البيانات
1. `plans.seat_price_yearly_sar` جديد، و`seat_price_sar` صار NULL-able (صار «الشهري»).
2. `subscriptions.billing_cycle` جديد — يُملأ من دورة الباقة التي كان الاشتراك عليها،
   فلا اشتراك يغيّر دورته الفعلية.
3. **دمج الزوج المبذور**: `monthly` (شهري) + `yearly` (سنوي) وجهان لمنتج واحد بسعري
   400/4080 — يُدمجان في باقة `standard` «قياسية» تحمل السعرين، وتُنقل إليها اشتراكاتهما
   بدورها المحفوظة، ثم يُحذف الصفّان. الدمج مشروط بوجودهما بهذين الرمزين حصراً
   (وهما رمزا البذر) — أي باقة أخرى تبقى كما هي بسعرها في خانة دورتها.
4. `plans.billing_cycle` يسقط — لم يعد للباقة دورة.

idempotent: كل خطوة بـIF [NOT] EXISTS أو مشروطة بوجود الصفوف.

Revision ID: 0022
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

SQL = r"""
-- ═══ 1) عمودا السعر على الباقة ═══
ALTER TABLE plans ADD COLUMN IF NOT EXISTS seat_price_yearly_sar NUMERIC(12,2);
ALTER TABLE plans ALTER COLUMN seat_price_sar DROP NOT NULL;

-- ═══ 2) عمود الدورة على الاشتراك ═══
ALTER TABLE subscriptions
    ADD COLUMN IF NOT EXISTS billing_cycle billing_cycle NOT NULL DEFAULT 'monthly';

-- ═══ 3) الدورة تنتقل من الباقة إلى الاشتراك، وسعر الباقة السنوية إلى خانته ═══
-- ديناميكي لا ساكن: قاعدة جديدة بناها 0001 من النماذج الحالية لا تملك plans.billing_cycle
-- أصلاً، وPostgreSQL يحلّل الجملة كاملة فيسقط SQL ساكن يذكر عموداً غائباً ولو داخل IF.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'plans' AND column_name = 'billing_cycle') THEN
        EXECUTE 'UPDATE subscriptions s SET billing_cycle = p.billing_cycle
                 FROM plans p WHERE p.code = s.plan';
        EXECUTE 'UPDATE plans SET seat_price_yearly_sar = seat_price_sar, seat_price_sar = NULL
                 WHERE billing_cycle = ''yearly'' AND seat_price_yearly_sar IS NULL';
    END IF;
END $$;

-- ═══ 4) الباقة لم تعد دورة ═══
-- **قبل الدمج لا بعده**: العمود NOT NULL، وصف standard الجديد لا دورة له فيسقط الإدراج
-- (كشفه تشغيل الهجرة على نسخة من قاعدة حيّة قبل النشر).
ALTER TABLE plans DROP COLUMN IF EXISTS billing_cycle;

-- ═══ 5) دمج الزوج المبذور monthly+yearly في باقة standard ═══
DO $$
DECLARE
    monthly_price NUMERIC(12,2);
    yearly_price  NUMERIC(12,2);
    merged_features JSONB;
BEGIN
    SELECT seat_price_sar INTO monthly_price FROM plans WHERE code = 'monthly';
    -- COALESCE يغطي المسارين: بعد الخطوة 3 السعر في الخانة السنوية، وإن لم تجرِ فهو في الشهرية
    SELECT COALESCE(seat_price_yearly_sar, seat_price_sar) INTO yearly_price
    FROM plans WHERE code = 'yearly';
    IF monthly_price IS NULL AND yearly_price IS NULL THEN
        RETURN;  -- لا زوج مبذور (قاعدة جديدة أو رُحّلت سابقاً)
    END IF;

    -- المميزات: ما على الشهرية أولاً (هي المُسندة للمنشآت عملياً)، وإلا ما على السنوية
    SELECT COALESCE(
        (SELECT features FROM plans WHERE code = 'monthly'),
        (SELECT features FROM plans WHERE code = 'yearly')
    ) INTO merged_features;

    INSERT INTO plans (id, code, name_ar, name_en, seat_price_sar, seat_price_yearly_sar,
                       is_active, features, created_at, updated_at)
    VALUES (gen_random_uuid(), 'standard', 'قياسية', 'Standard',
            monthly_price, yearly_price, TRUE, merged_features, now(), now())
    ON CONFLICT (code) DO UPDATE
        SET seat_price_sar        = COALESCE(plans.seat_price_sar, EXCLUDED.seat_price_sar),
            seat_price_yearly_sar = COALESCE(plans.seat_price_yearly_sar, EXCLUDED.seat_price_yearly_sar);

    -- الاشتراكات تنتقل للباقة الجديدة بدورتها المحفوظة في الخطوة 3
    UPDATE subscriptions SET plan = 'standard' WHERE plan IN ('monthly', 'yearly');
    DELETE FROM plans WHERE code IN ('monthly', 'yearly');
END $$;

-- ═══ 6) تطبيع باقة العرض المقلّصة: basic-monthly (اسمٌ يحمل دورة) → basic بسعرين ═══
-- بُذرت قبل ساعات في العمل نفسه ولم تُسند لأي منشأة؛ بلا هذا يعرض الكونسول صفّين لباقة واحدة
-- (القديمة + basic التي يبذرها seed الجديد). مشروط بألا اشتراك عليها — لا افتراض عن حالة العميل.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM plans WHERE code = 'basic-monthly')
       AND NOT EXISTS (SELECT 1 FROM plans WHERE code = 'basic')
       AND NOT EXISTS (SELECT 1 FROM subscriptions WHERE plan = 'basic-monthly') THEN
        UPDATE plans
        SET code = 'basic',
            name_ar = 'أساسية',
            name_en = 'Basic',
            seat_price_yearly_sar = COALESCE(seat_price_yearly_sar, seat_price_sar * 10.2)
        WHERE code = 'basic-monthly';
    END IF;
END $$;

-- باقة بلا سعر أصلاً لا معنى لها
ALTER TABLE plans DROP CONSTRAINT IF EXISTS ck_plans_has_price;
ALTER TABLE plans ADD CONSTRAINT ck_plans_has_price
    CHECK (seat_price_sar IS NOT NULL OR seat_price_yearly_sar IS NOT NULL);

-- وضع القراءة لدور التطبيق كما ثبّتته 0021 (الفوترة وحسم المميزات يقرآن الباقة)
GRANT SELECT ON plans TO medify_app;
REVOKE INSERT, UPDATE, DELETE ON plans FROM medify_app;
"""

DOWN_SQL = r"""
ALTER TABLE plans DROP CONSTRAINT IF EXISTS ck_plans_has_price;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS billing_cycle billing_cycle NOT NULL DEFAULT 'monthly';
UPDATE plans SET billing_cycle = 'yearly' WHERE seat_price_sar IS NULL;
UPDATE plans SET seat_price_sar = seat_price_yearly_sar WHERE seat_price_sar IS NULL;
ALTER TABLE plans ALTER COLUMN seat_price_sar SET NOT NULL;
ALTER TABLE plans DROP COLUMN IF EXISTS seat_price_yearly_sar;
ALTER TABLE subscriptions DROP COLUMN IF EXISTS billing_cycle;
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    """تراجع بأفضل جهد: الباقة تعود دورةً واحدة (السعر الثاني يضيع — لا مكان له في الشكل القديم)."""
    op.execute(DOWN_SQL)
