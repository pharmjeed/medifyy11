# سياسة الاحتفاظ الموحّدة — Medify (المرحلة 8 من التحصين، 2026-08-03)

المرجع التنفيذي: `backend/app/services/retention.py` · الجدولة: مهمة arq ليلية
(`app/worker.py: retention_nightly` — 02:30 UTC) أو يدوياً `scripts/purge_recordings.py`.

## المدد الافتراضية (قابلة للتجاوز لكل منشأة من `PATCH /api/v1/settings/retention`)

| النوع (`artifact_type`) | ما يشمله | الافتراضي |
|---|---|---|
| `audio` | ملفات WAV/FLAC للتسجيلات (`recordings`) | 90 يوماً |
| `transcript_raw` | التفريغ الخام + diarization (صف `transcripts` كاملاً) | 90 يوماً |
| `intermediate_drafts` | تعديلات الكتابة/الإملاء (`edit_events` typing/voice) + سجل محاولات المعالجة (`processing_attempts`) | 30 يوماً |
| `ai_chat_logs` | محادثات التعديل (`edit_events` قناة ai_chat) | 90 يوماً |
| `note_versions_uploaded` | لقطات النسخ المنقولة (`note_versions` بحالة uploaded) | 365 يوماً |
| `audit_log` | سجل التدقيق (`audit_logs`) | 3650 يوماً (10 سنوات) |
| `aggregated_metrics` | المقاييس المجمّعة | **بلا حذف** (`NULL`) |

`retention_days = NULL` في أي تجاوز يعني «بلا حذف» لهذا النوع.

## الآلية: soft ثم hard بسماح 7 أيام

1. **soft-delete**: عند انقضاء المدة يُوسم الأثر (`deleted_at`) ويبقى قابلاً
   للاسترجاع تشغيلياً طوال فترة السماح (`GRACE_DAYS = 7`).
2. **hard-delete**: بعد 7 أيام من الوسم يُتلف فعلياً — ملف الصوت يُحذف من القرص،
   وصفوف التفريغ/الأحداث/النسخ تُحذف من القاعدة.
3. الجداول الإلحاقية (`audit_logs`, `note_versions`) محمية بـ triggers لا تسمح
   بالحذف إلا عبر **صمام الاحتفاظ** `medify.retention='purge'` الذي تضبطه مهمة
   الكنس حصراً بدور المالك (دور التطبيق محجوب بـ REVOKE أصلاً).
4. **كل حذف يكتب Audit**: النوع + العدد + النطاق (`retention.soft_deleted` /
   `retention.hard_deleted` / `recording.purged`) — **بلا محتوى إطلاقاً**، والفاعل
   `النظام` (مهمة دورية).

## القواعد الحاكمة

- **`visits.legal_hold`** (يضبطه الأدمن من `POST /api/v1/visits/{id}/legal-hold`):
  يجمّد كل حذف احتفاظي لأثار الزيارة كلياً — لا soft ولا hard ما دام مرفوعاً،
  وكل تغيير له مدوَّن في التدقيق (`visit.legal_hold_set`).
- **الزيارات المُبطلة (voided)** تتبع أقصر مدة مطبّقة في المنشأة (افتراضياً 30
  يوماً — مدة `intermediate_drafts`) لأثارها الصوتية والتفريغية.
- **اللقطة المنقولة داخل مدتها لا تُمس** — والحذف بعد المدة لا يمس سجل التدقيق
  الذي يوثّق تاريخها (لسجل التدقيق مدته العشرية المستقلة).

## المراقبة

`GET /api/v1/admin/retention-status`: ما سيُحذف خلال 7 أيام (لكل نوع) + الموسوم
بانتظار الحذف الصلب + عدد الزيارات المجمّدة قانونياً — أعداد فقط بلا محتوى.
