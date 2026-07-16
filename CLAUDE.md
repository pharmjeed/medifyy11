# Medify — Saudi Ambient AI Medical Scribe

منصة كاتب طبي ذكي محيطي ثنائية اللغة (عربي → SOAP → ترميز → رفع لنظام المستشفى).
Monorepo: `frontend/` (Next.js 14 App Router + TS strict) · `backend/` (FastAPI + Python 3.12 + SQLAlchemy 2) · `infra/` (Docker Compose + Caddy + Oracle deploy) · `scripts/` (seed + smoke).

## العقد (مصادر الحقيقة — لا اجتهاد خارجها)

| المجال | المرجع | الخلاصة |
|---|---|---|
| الشاشات | DOC-10 v1.2 | 42 مواصفة (W-001..006, W-101..112, W-201..224) في **15 صفحة** حصراً |
| قاعدة البيانات | DOC-04 v1.1 | 23 جدولاً حصراً — لا جدول/عمود خارجها · UUID v7 · RLS على كل جدول مستأجري |
| API | DOC-05 v1.1 | القاعدة `/api/v1` — لا نقطة نهاية خارجها · غلاف `{data,meta}` / `{error:{code,message_ar,message_en,details}}` |
| الأخطاء | DOC-13 v1.2 | **24 رمز MDF حصراً** (22 السابقة + 4015 «2FA مطلوب/خاطئ» + 4229 «آخر مالك فعّال» — اعتماد DOC-20) |
| الإشعارات | DOC-12 | **12 حدثاً حصراً** (dr.* ×6 + ad.* ×6) |
| الصلاحيات | DOC-06 v1.1 | دوران فقط admin/doctor · ثلاث طبقات: API guard → RLS → قيود القاعدة |
| التصميم | DOC-11 + النموذج المفكوك | ألوان/خطوط/مكونات مقفولة · IBM Plex Sans Arabic self-hosted |
| التتبع | DOC-14 | 12 حدثاً تحليلياً — لا محتوى سريري ولا معرف مريض |
| السوبر أدمن | DOC-20 v1.1 (معتمدة 2026-07-16) | كونسول مالك المنصة: شاشات W-SA-01..15 · درجات خمس · 2FA · سجل موحّد — مصدر الحقيقة لطبقة `/sa` |

## المحظورات الملزمة (DOC-07 §٢)

- **لا Tailwind / Bootstrap / أي إطار CSS خارجي** — التنسيق من `frontend/styles/tokens.css` فقط.
- **TypeScript strict** بلا `any` غير مبرر.
- لا نقطة API / جدول / شاشة خارج الوثائق.
- **لا خروج بيانات قبل الاعتماد البشري** — يُفرض بقيد FK: `upload_jobs.visit_id → approvals.visit_id`.
- **الأدمن لا يقرأ محتوى سريرياً نصياً أبداً** — عدادات وتجميعات فقط.
- `approvals` و`audit_logs` إلحاقية فقط (REVOKE + triggers).
- لا محتوى سريري نصي في اللوجات أو التحليلات.
- لا أسرار في الكود أو المستودع.
- لا تطبيق إرشاد AI تلقائياً — فعل صريح من الدكتور فقط.

## قرارات مقفولة (مالك 2026-07-14)

- المرضى **بالمزامنة حصراً** — لا API ولا واجهة إنشاء/تعديل مريض.
- آلة حالات الزيارة: `draft → recording → transcribed → summarized → in_review → approved → uploaded | upload_failed` + `cancelled` نهائية من `draft/recording` فقط (trigger).
- أقسام المراجعة تُبنى **ديناميكياً من بنية القالب** — لا S/O/A/P مثبتة.
- الدكتور يعدّل نص الإرشاد **ورمزه معاً** عند الحسم بالتعديل.
- أنظمة الترميز: ICD10AM (لا يُعطَّل — CHECK) + ACHI + SBS + SFDA.
- desktop-first، RTL افتراضاً، كل مقطع لاتيني داخل `<bdi>`.

## طبقة السوبر أدمن (قرار مالك 2026-07-15 — تعديل معتمد على DOC-04/05/06/09/10)

- **دور ثالث فوق المنشآت**: `super_admin` لمالك ميديفاي — جدول `platform_admins` مستقل (ليس في `users`؛ قيد الدورين يبقى). JWT بـ `scope=platform` بلا `facility_id` — مرفوض في مسارات المنشآت والعكس صحيح (`deps.super_admin_only`).
- **جدولان جديدان** (هجرة 0002): `platform_admins` (محجوب كلياً عن medify_app) و`plans` (كتالوج الباقات — SELECT فقط لدور التطبيق). `subscriptions.plan` يشير تطبيقياً إلى `plans.code`. `seat_events.actor_user_id` أصبح NULL-able (NULL = فعل المنصة).
- **API**: كل شيء تحت `/api/v1/sa/*` بمحرك النظام (يتجاوز RLS بقيود صريحة): auth (login/refresh/logout/me) · overview · facilities (قائمة/تفاصيل/حالة/اشتراك) · users (إنشاء أدمن/دكتور، تفعيل/تعطيل، إعادة كلمة مرور) · plans (CRUD — الرمز ثابت) · invoices (قائمة/إصدار/تسوية يدوية paid/void/overdue).
- **الفوترة حسب الدكاترة**: فاتورة الدورة = عدد الدكاترة النشطين × `plans.seat_price_sar` + VAT 15% مفصولة (`billing.plan_seat_price` مع احتياطي 400). تغيير الباقة/المقاعد من المنصة **لا** يُصدر فاتورة تلقائياً — الإصدار فعل صريح. التسوية اليدوية ترفع تعليق المنشأة إن لم تبقَ متأخرات؛ لا تراجع عن paid.
- **السوبر أدمن لا يقرأ محتوى سريرياً أبداً** — نفس قيد أدمن المنشأة: عدادات وتجميعات فقط. كل فعل منصةٍ يُدوَّن في `audit_logs` منشأته بـ `actor_user_id=NULL` + `meta.sa`.
- **الواجهات**: `/sa/login` · `/sa` (نظرة) · `/sa/facilities[/:id]` · `/sa/plans` · `/sa/invoices` — هيكل `SaShell` بشارة ذهبية وجلسة مستقلة (`lib/sa.ts`).
- **البذر**: dev عبر `scripts/seed.py` (حساب `owner` — يتطلب `SEED_SUPER_ADMIN_PASSWORD`) · الإنتاج عبر `scripts/create_super_admin.py` (كلمة المرور من `SUPER_ADMIN_PASSWORD`).

## اعتماد DOC-20 + تعديلا المالك (2026-07-16)

- **DOC-20 v1.1 معتمدة** — مصدر الحقيقة لطبقة السوبر أدمن (شاشات W-SA، درجات، 2FA، سجل موحّد، خطة مراحل).
- **تعديل ١ — ترابط المنصات الثلاث**: سوبر أدمن + أدمن منشأة + دكتور كيان واحد؛ كل فعل منصّي يسري فوراً عبر الطبقات (تعليق→منع دخول MDF-4013، تعطيل دكتور→تحرير مقعد، تكلفة الدكتور→فواتير لاحقة واشتراك المنشأة) — يُختبر الترابط لا الطبقة وحدها.
- **تعديل ٢ — الاشتراك بعدد الدكاترة فقط**: لا باقات ميزات؛ المنشأة تحدد عدد الدكاترة (حقل كتابة + عدّاد معاً في التسجيل والاشتراك)، و**تكلفة كل دكتور من السوبر أدمن** (`plans` = دورات فوترة شهري/سنوي بسعر للدكتور). واجهاتياً «دكتور/عدد الدكاترة» بدل «مقعد» — الأسماء التقنية (`seats_total`) تبقى.
- **المرحلة 1 (حوكمة/أمان — هجرة 0003)**: `platform_admins.role` بخمس درجات (owner/ops/finance/support/read_only — الكتالوج/الأسعار وإدارة الحسابات للـowner حصراً) · TOTP 2FA (سرّ مشفّر عموداً + رموز استرداد هاش) إلزامي على الإنتاج (`environment=production`؛ dev اختياري) · إعادة مصادقة TOTP بترويسة `X-SA-Reauth` للإجراءات الحساسة · جدول `platform_audit_logs` إلحاقي موحّد (تدوين مزدوج مع سجل المنشأة) · حماية آخر owner فعّال (MDF-4229) · نقاط `/sa/me/2fa/*`، `/sa/admins`، `/sa/audit`.

## المحركات القابلة للتبديل (متغيرات بيئة)

- `STT_ENGINE=whisper|mock` · `LLM_ENGINE=claude|mock` (نموذج claude-sonnet-4-5)
- `INTEGRATION_ENGINE=mock|http` (وجهة رفع المستشفى) · `EMAIL_ENGINE=mock|smtp`
- `ANALYTICS_ENGINE=log|posthog` — الأحداث بلا محتوى سريري
- المطالبات في `backend/app/prompts/` بإصدارات (`P2-summary@1.0` …) — تُسجَّل مع كل استدعاء.

## أوامر التشغيل

```bash
# تشغيل كامل محلي
cd infra && docker compose up --build
# باك اند فقط (dev)
cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload
# هجرات + بذر
cd backend && alembic upgrade head && python ../scripts/seed.py
# اختبارات
cd backend && pytest                      # يتطلب Postgres (TEST_DATABASE_URL)
cd frontend && npm run typecheck && npm run build
cd frontend && npx playwright test        # e2e
# فحص دخاني
bash scripts/smoke.sh http://localhost:8000
```

## بيانات seed (مطابقة للنموذج التفاعلي)

منشأتان (الثانية لاختبار العزل) · أدمن: أ. سلطان الحربي · 3 دكاترة منهم د. نورة العتيبي · عيادتان · 20 مريضاً «متزامناً» · 5 قوالب جاهزة · زيارات بحالات متنوعة.
