# Medify — Saudi Ambient AI Medical Scribe

منصة كاتب طبي ذكي محيطي ثنائية اللغة للسوق السعودي: تستمع للاستشارة العربية، تفرّغها فورياً، تلخّصها بنظام <bdi>SOAP</bdi> وفق قالب الدكتور، تحلّلها على ضوء ملف المريض بإرشاد سريري وترميزي مدمج (<bdi>ICD-10-AM / ACHI / SBS / SFDA</bdi>)، وترفعها لنظام المستشفى بصيغة <bdi>FHIR/NPHIES</bdi> — **عبر بوابة اعتماد بشري نهائية إلزامية، ولا تغادر أي بيانات النظام قبلها**.

## التشغيل السريع (Docker)

```bash
cd infra
docker compose up --build          # postgres16 + redis + backend + frontend
docker compose run --rm seed       # بيانات تجريبية (منشأتان، دكاترة، 20 مريضاً، زيارات)
```

- الواجهة: http://localhost:3000 · الـAPI: http://localhost:8000/api/v1 · وثائق: `/api/v1/docs`
- دخول تجريبي: منشأة `1010456789` — أدمن `admin` / `Admin@12345` — دكتور `dr.ahmad` / `Doctor@12345`

## التطوير المحلي

```bash
# backend (يتطلب PostgreSQL 16 بدورين medify_owner و medify_app — انظر infra/postgres-init.sql)
cd backend && pip install -e ".[dev]"
alembic upgrade head && python ../scripts/seed.py
uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm run dev
```

## الاختبارات

```bash
cd backend && pytest               # 62 اختباراً ضد PostgreSQL حقيقي (RLS/triggers/E2E)
cd frontend && npm run typecheck && npm run build
cd frontend && npx playwright test # الرحلة الكاملة e2e
bash scripts/smoke.sh http://localhost:8000   # فحص دخاني 15 خطوة عبر curl
```

## النشر على Oracle Cloud

```bash
cp deploy.env.example deploy.env   # واملأ ORACLE_HOST وORACLE_SSH_KEY (وDOMAIN اختيارياً)
bash infra/deploy/oracle.sh        # idempotent: production على 80/443 + staging على 8080
```

## المحركات القابلة للتبديل

| المتغير | القيم | الافتراضي |
|---|---|---|
| `STT_ENGINE` | `whisper` (faster-whisper small int8) / `mock` | mock |
| `LLM_ENGINE` | `claude` (يتطلب `ANTHROPIC_API_KEY`) / `mock` | mock |
| `INTEGRATION_ENGINE` | `http` (وجهة FHIR حقيقية) / `mock` | mock |
| `PAYMENT_ENGINE` / `EMAIL_ENGINE` | `mock` | mock |
| `NEXT_PUBLIC_SHOW_SPEC_IDS` | إظهار شارات المواصفات W-XXX | true (dev) |

## البنية والعقد

- **الوثائق الحاكمة:** 19 وثيقة معتمدة (DOC-01..19) — الشاشات حصراً 42 مواصفة في 15 صفحة (DOC-10 v1.2)، القاعدة حصراً 24 جدولاً (DOC-04 v1.1)، الأخطاء حصراً 22 رمز MDF (DOC-13 v1.1).
- **العزل بثلاث طبقات:** حارس دور على كل نقطة API ← RLS على مستوى PostgreSQL (عزل منشآت + نطاق دكتور + حجب المحتوى السريري عن الأدمن) ← قيود القاعدة (آلة حالات الزيارة، إلحاقية approvals/audit_logs، لا upload_job بلا approval عبر FK).
- التفاصيل الكاملة في [CLAUDE.md](CLAUDE.md) وسجل القرارات في [docs/DECISIONS.md](docs/DECISIONS.md).
