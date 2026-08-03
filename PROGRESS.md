# PROGRESS — مهمة التحصين الشامل (19 مرحلة)

الفرع: `feature/full-hardening` (يُنشأ عند «نفّذ») · بدأت: 2026-08-03 · المرجع: توجيه المالك + `CLAUDE.md` §«مهمة التحصين الشامل»

## جدول المراحل

| # | المرحلة | الحالة | ملاحظات |
|---|---------|--------|---------|
| 0 | استكشاف وخطة | ✅ أُنجزت — بانتظار «نفّذ» | ثلاثة تقارير استكشاف + خطة معروضة على المالك |
| 1 | توسعة آلة الحالات | ✅ أُنجزت | هجرة 0011: `reopened` + دورة `uploaded→reopened→in_review` + `voided` من summarized/approved · خطاف Audit موحّد `visit.state_changed` في `transition()` بفاعل (uploader عبره أيضاً) · 5 اختبارات جديدة (146 passed) |
| 2 | الرفع المجزّأ | ✅ أُنجزت | هجرة 0012 `audio_chunks` (قيد فريد visit+index، sha256، offset/length) · ترقيم موحّد معمَّر عبر الاتصالات (idempotent re-ack — قتل ثغرة تكرار الصوت) · reconcile ذاتي الشفاء عند الاتصال · finalize صارم في stop (لا-فجوات/حجم/bit-exact → MDF-4234 جديد 409) · واجهة: sha256 لكل مقطع + backoff أُسّي + لافتة «استئناف تسجيل منقطع» بعد قتل التبويبة · 5 اختبارات جديدة (151 passed) |
| 3 | إعادة المحاولة التلقائية | ✅ أُنجزت | هجرة 0013 `processing_attempts` (يُكتب بجلسة نظام — ينجو من rollback) · مصنّف مبني على الأنواع (`pipelines/classify.py` — أصلح عدّ FileNotFoundError عابراً) · `services/processing.py`: محاولة + 3 إعادات 30ث/2د/5د على العابر فقط، non_retryable فوري، فشل P3 غير معطِّل · وضعان: inline (dev/tests) وqueue (عامل arq بخدمة worker في compose) · نقطتا `processing-status` و`reprocess` + استطلاع الواجهة بتقدم صادق · 4 اختبارات (155 passed) |
| 4 | الإبطال (Void) | ✅ أُنجزت | المصادر الموسّعة summarized/in_review/approved-قبل-النقل (trigger 0011 + API) · RBAC: الدكتور صاحب الزيارة أو الأدمن (سياسة doctor_scope تمرّره) · exports → 410 بكود MDF-4235 الجديد · reason enum بمصادقة Pydantic (422 قياسي بدل 404 الخاطئ) + توافق عكسي «test» · from_state/actor_role في Audit · 3 اختبارات جديدة + تحديثان (158 passed) |
| 5 | فتح البوابة ① (Unlock) | ✅ أُنجزت | الأساس القائم (0010) اكتمل: MDF-4236 الجديد (409) لحاجزي بعد-② وحالة-غير-مسموحة · مقارنة hash في الملخص (`note_unlock.text_unchanged`) — لم يتغيّر → «إعادة اعتماد بنقرة» بواجهة مميزة · قرارات الإرشادات محفوظة (مثبت سلفاً) · اختبار دورة hash كامل (159 passed) |
| 6 | دورة النسخ (Reopen) | ✅ أُنجزت | هجرة 0014: `note_versions` (لقطات مشفّرة + بصمة حزمة + طوابع بوابتين + diff + سبب reopen) بtrigger تجميد بعد النقل · «الدورة» cycle على visits/note_approvals/approvals وtriggers 0010 صارت واعية بها · upload_jobs يربط approval_id مباشرة (مهمة لكل نسخة) · POST reopen (من uploaded، سبب إلزامي، مسودة v+1) · FHIR: entry.request صالح R4 + DocumentReference + amended + relatesTo/replaces للسابقة حصراً + ifNoneExist · محوّل HL7 MDM (T02/T09) + عميل MLLP + محرك hl7 · exports ?version= من اللقطات + تذييل النسخة + فصل retry-upload الصارم · واجهة: زر reopen + مودال + لافتة النسخة · 5 اختبارات (164 passed) |
| 7 | Idempotency واعٍ بالنسخة | ✅ أُنجزت | هجرة 0015: `upload_jobs.idempotency_key` فريد ("{visit}:{version}" — backfill للقائم) + جدول `delivery_receipts` (فريد على مفتاح+وجهة) · الفحص قبل أي إرسال: إيصال قائم = نجاح مُعاد بلا إرسال (مُثبت باختبار «وجهة فاشلة + إيصال مزروع → نجاح») · الإيصال يُكتب فور الاستقبال بجلسة نظام · ifNoneExist وMSH-10 من م6 يكملان الدفاع بالطرف البعيد · 4 اختبارات (168 passed) |
| 8 | سياسة الاحتفاظ الموحّدة | ✅ أُنجزت | هجرة 0016: `retention_policies` لكل منشأة (الافتراضات: audio/transcript 90 · وسيطة 30 · ai_chat 90 · نسخ منقولة 365 · تدقيق 3650 · مجمّعة بلا حذف) + `visits.legal_hold` + `transcripts.deleted_at` + صمام `medify.retention='purge'` في triggers الإلحاقية · كنس موحّد soft→hard بسماح 7 أيام مع Audit (نوع+عدد بلا محتوى) · المُبطلة على الأقصر · نقاط GET/PATCH `/settings/retention` + `/admin/retention-status` + `POST /visits/{id}/legal-hold` · cron ليلي في العامل + توافق خلفي للسكربت · `docs/retention-policy.md` · 4 اختبارات جديدة + تحديث القديم (172 passed) |
| 9 | أرشفة FLAC | ✅ أُنجزت | `services/audio_archive.py`: WAV→FLAC بعد P1 بتحقق إلزامي (بصمة عينات PCM المفكوكة تُطابق الأصل قبل أي حذف؛ فشل = WAV باقٍ + إنذار Audit) · ffmpeg في صورة الباك اند · مربوطة بخط المعالجة خلف `FLAC_ARCHIVE=auto` (off في الاختبارات — حماية bit-exact التدفق) · سكربت دفعات ليلية `archive_flac_backfill.py` للأرشيف القائم · اختباران بترميز حقيقي (174 passed) |
| 10 | إظهار السند | ✅ أُنجزت | P2-verify@1.1: الحذف يبقى + الربط جملة↔مقاطع يُعاد ويُحفظ (كان يُرمى) · التخزين JSONB مشفّر مضمّن `summary_sections.evidence_json` (هجرة 0017 — المبرَّر: يُقرأ دائماً مع قسمه، لا استعلام عبر الزيارات) · أزمنة ms من P1 حرفياً · تعديل يدوي (كتابة/إملاء/AI chat) → `refresh_section_evidence` يوسم الجديد «تحرير طبيب» · GET `/visits/{id}/evidence` + `/visits/{id}/audio` بـ HTTP Range وtoken (وسم audio لا يحمل ترويسات) · واجهة: جمل قابلة للنقر 🎧 + مشغّل مضمّن ±1ث + إبراز مقطع التفريغ + وسما «بلا مصدر صوتي»/«تحرير طبيب» · 3 اختبارات (177 passed) |
| 11 | إبراز الثقة المنخفضة | ✅ أُنجزت | Whisper: `avg_logprob`/`no_speech_prob` تُلتقطان وتُطبَّعان 0–1 (كانتا مُهدرتين) · ثقة الجملة = **أدنى** مقاطعها (تشاؤم مقصود) داخل سند م10 · عتبات من `platform_settings` عبر `/sa/settings/stt-confidence` — تسري فوراً بلا deploy · واجهة: خط سفلي متقطع بدرجتين (أزرق/أحمر — **لا كهرماني**) + tooltip «اسمع المصدر» + شريط «جودة الصوت منخفضة» · الدرجات في telemetry أرقاماً · 4 اختبارات (181 passed) |
| 12 | محرك جاهزية المطالبة | ✅ أُنجزت | `services/claim_readiness.py` مستقل + `backend/rules/*.yaml` بأربعة أنواع declarative (medical_necessity · mds_completeness · code_composition · prior_auth) موثّقة بأمثلة في `rules/README.md` — إضافة قاعدة بلا deploy (يُعاد التحميل بتغيّر mtime) · MDF-4237 الجديد يمنع البوابة ② على أي block · واجهة الربط: `PATCH /guidance-items/{id}/link-diagnosis` (يقبل تشخيصات الزيارة فقط) + قائمة اختيار ذكية · `GET /visits/{id}/claim-readiness` يعمل مع كل تحميل/تغيير أكواد · نسبة العبور الأول في telemetry · 5 اختبارات (186 passed) |
| 13 | رفض المتبقي دفعة واحدة | ✅ أُنجزت | `POST /visits/{id}/guidance/reject-remaining` — كل إرشاد سطر Audit فردي مستقل (`guidance.rejected`) بـ`bulk_action_id` مشترك + حدث telemetry لكل بند · صفر معلّق = لا فعل ولا معرّف · الرد يحمل جاهزية المطالبة المحدَّثة · الواجهة: زر يظهر عند معلّق>0 فقط + مودال يعرض القائمة قبل التأكيد · 3 اختبارات (189 passed) |
| 14 | ملخص المريض بالعربي | ✅ أُنجزت | برومبت `P6-patient-summary@1.0` بخمسة أقسام ثابتة + تعليمة «لا تضف أي معلومة غير موجودة في المصدر» · هجرة 0018: يُخزَّن مع النسخة (`note_versions`) بقرار تضمين وبصمة نص · لا توليد قبل البوابة ① (MDF-4231 في طبقة الخدمة) · unlock/تعديل → `stale` حتى إعادة التوليد · reopen → النسخة الجديدة تبدأ بلا ملخص · PDF عربي RTL كامل بخط IBM Plex (endpoint مستقل) + ظهوره في مخارج النسخة عند التضمين فقط · واجهة: لوحة معاينة/تعديل لكل قسم + toggle · 4 اختبارات (193 passed) |
| 15 | القياس الآلي | ✅ أُنجزت | هجرة 0019: `metric_events` (أرقام حصراً — الحارس التطبيقي يرفض النص والبوليان) + `daily_metrics` · edit_distance بـLevenshtein على مستوى الكلمات منسّبة 0–1 إجمالية ولكل قسم (الـdiff يُحسب بالذاكرة ويُرمى) · الأزمنة (stop→اعتماد نهائي، وقت المراجعة) · نسب P3 · reopen · claim_readiness_first_pass · تجميع ليلي (cron 03:00 + سكربت) واللوحات تقرأ من المجمَّع · `GET /admin/metrics/summary` بـRBAC أدمن · 7 اختبارات منها فحص آلي لغياب أي حقل نصي (200 passed) |
| 16 | طابور المذكرات المعلّقة | ⬜ لم تبدأ | «بانتظارك» 4 مجموعات + تذكير يومي + تقرير مدير طبي |
| 17 | سحب سياق المريض | ⬜ لم تبدأ | خلف feature flag — البنية جزئياً قائمة (`patient_context_snapshots`) |
| 18 | جاهزية Streaming | ⬜ لم تبدأ | refactor P1 لواجهة مقاطع + اختبار تكافؤ بمرجع محفوظ مسبقاً |
| 19 | الوثائق | ⬜ لم تبدأ | integration-spec + runbook + retention + contract-clauses + تدقيق التذييل |

## سجل الهجرات (للمراجعة اليدوية)

| الهجرة | المرحلة | الوصف | downgrade |
|--------|---------|-------|-----------|
| 0011_state_machine_expansion | 1 | قيمة `reopened` + استبدال `enforce_visit_state_machine` (مصادر voided الموسّعة + دورة reopen) | يعيد دالة 0008؛ قيمة enum تبقى معزولة (قيد PostgreSQL) |
| 0012_audio_chunks | 2 | جدول `audio_chunks` بقيد فريد (visit_id, chunk_index) + sha256 + offset/length + RLS قياسي | drop table + الفهارس |
| 0013_processing_attempts | 3 | جدول `processing_attempts` (stage/attempt_no/error_class/error_detail بلا PHI/أزمنة) + RLS قياسي | drop table + الفهارس |
| 0014_note_versions | 6 | `note_versions` + trigger تجميد المنقولة + عمود cycle (visits/note_approvals/approvals) + approvals فريد (visit,cycle) + upload_jobs→approval_id + إعادة تعريف ثلاث دوال 0010 بوعي الدورة | يعيد دوال 0010 ويسقط note_versions؛ أعمدة cycle تبقى (بيانات) |
| 0015_idempotency_receipts | 7 | `upload_jobs.idempotency_key` فريد + backfill + جدول `delivery_receipts` بقيد (مفتاح، وجهة) | يسقط الجدول والعمود والقيد |
| 0016_retention_unified | 8 | `retention_policies` + `visits.legal_hold` + `transcripts.deleted_at` + صمام retention في `forbid_mutation` (audit_logs حصراً) و`forbid_uploaded_version_mutation` | يعيد الدوال الصارمة ويسقط الجدول والأعمدة |
| 0017_evidence_links | 10 | `summary_sections.evidence_json` (نص مشفّر تطبيقياً — سند الجمل) | يسقط العمود |
| 0018_patient_summary | 14 | `note_versions`: `patient_summary_json` (مشفّر) + `patient_summary_included` + `patient_summary_note_hash` | يسقط الأعمدة الثلاثة |
| 0019_metric_events | 15 | `metric_events` (إلحاقي: REVOKE UPDATE/DELETE) + `daily_metrics` + RLS قياسي | يسقط الجدولين |

## أكواد MDF الجديدة

| الكود | المرحلة | المعنى |
|-------|---------|--------|
| MDF-4234 | 2 | 409 — ملف الصوت غير مكتمل/غير مطابق عند finalize (قائمة الناقص في details) |
| MDF-4235 | 4 | 410 — مخارج زيارة مُبطلة (Void ختمٌ للمحتوى) |
| MDF-4236 | 5 | 409 — حاجز Unlock بنيوي: البوابة ② أُنجزت أو الحالة لا تسمح (المسار Addendum/Reopen) |
| MDF-4237 | 12 | 422 — جاهزية المطالبة غير مكتملة (بنود حاجبة في details) — نمط MDF-4222 |

## قرارات اتُّخذت منفرداً

- (م0) خريطة أسماء آلة الحالات: مرجع التوجيه يُنفَّذ فوق enum المطبَّق + البوابتين كجداول — لا إعادة تسمية شاملة (التبرير في CLAUDE.md §المهمة).
- (م1) `upload_failed` ليست مصدر إبطال — المواصفة تحصر المصادر الأربعة؛ مسارها retry-upload ثم reopen. مثبَّت باختبار.
- (م1) انتقالات النظام (نتيجة الرفع) تُدوَّن بفاعل NULL = «النظام»؛ ترتيب audit-logsصار بكاسر تعادل id (UUID v7) لأن أسطر المعاملة الواحدة تتشارك at.
- (م1) أصلحنا قبل الفرع (على main المدفوع): أعطال addendums.py الكاملة + سياسة RLS 0009 (app.scope غير مضبوط كان يكسر استعلامات الجدول) + MDF-4040 غير المعرّف في superadmin.
- (م2) أُبقي النقل عبر WS (لا REST chunks) — معايير القبول تحققت بسجل خادمي: التحقق النهائي داخل recording/stop لا endpoint منفصل. نشر الواجهة والخادم معاً إلزامي (بروتوكول الترقيم تغيّر من عدّاد-لكل-اتصال إلى عالمي).
- (م2) اختبار WS القديم «اتصال جديد = عدّاد جديد» حُدِّث رسمياً للسلوك المعمَّر — السلوك القديم هو ثغرة التكرار نفسها.
- (م2) العميل هو سلطة الإيقاف المؤقت: أُزيل تجاهل المقاطع الواردة أثناء pause خادمياً (كان يقدّم last_seq بلا كتابة — تناقض مع السجل).
- (م2) ملف الاختبار سُمّي test_streaming_chunks.py عمداً — اختبار العزل يثبّت إجمالي مرضى البذر (20) وكل الاختبارات المُنشئة للمرضى تأتي بعده أبجدياً (عرف الحزمة القائم).
- (م3) قرار «لا طوابير» (2026-08-02) فُسِّر على مقصده: لا تفريغ أثناء التسجيل ولا تأجيل للمعالجة — وضع queue يبدأ فوراً عند stop لكن خارج دورة الطلب (لا حجز HTTP وtransaction لدقائق backoff). inline يبقى للتطوير والاختبارات (بلا Redis).
- (م3) الإعادات داخل `process_visit_pipeline` لا عبر arq retries (سجل موحّد وتخطي مراحل مكتملة idempotent). الفشل النهائي في queue يُبقي الزيارة transcribed ويُستأنف بـ/reprocess؛ وفي inline يُرجعها rollback إلى recording (زر الإنهاء يعيد).
- (م3) نقطتا API جديدتان خارج DOC-05 بمقتضى المهمة: GET processing-status وPOST reprocess (+ حدث audit `visit.reprocess_requested`). المخرج غير المطابق للعقد من المحرك يُصنَّف non_retryable (فشل سريع).
- (م4) أسماء الحقول السلكية بقيت reason/note (لا reason_code/reason_text) — الدلالة نفسها وواجهة قائمة، مع قبول «test» القديم كمرادف test_recording. زر الإبطال في الواجهة يظهر لـsummarized/in_review (approved لحظية — الرفع فوري؛ إبطالها متاح API/أدمن).
- (م5) اسم النقطة بقي note-unlock (لا unlock-note) — منشور ومستخدم. «لا اعتماد نشط يُنقض» بقي MDF-4231 (422 أدق دلالة) وMDF-4236 (409) للحاجزين البنيويين — المواصفة طلبت كوداً جديداً للرفض وقد أُضيف.
- (م6) مفهوم «الدورة» cycle بدل تعقيد ربط الاعتمادات بالنسخ زمنياً: عدّاد على الزيارة يرتفع مع reopen وتحمله بوابتا كل نسخة — triggers القاعدة (تجميد/نشط واحد/حظر unlock بعد ②) صارت تفحص الدورة الحالية فقط. reopen ينفّذ uploaded→reopened→in_review في نداء واحد (المرور مسجَّل في audit).
- (م6) صف النسخة يُنشأ مسودةً عند reopen (يحمل سبب الفتح مشفّراً + نسخة لقطة السابقة) ويكتمل حرفياً لحظة البوابة ② — القيد «immutable» يسري بعد uploaded فقط (قبلها الحالة تتقدم draft→pending→uploaded/upload_failed).
- (م6) diff النسخ يُخزَّن كاملاً مشفّراً في note_versions.diff_json وAudit يحمل الأعداد فقط (visit.version_diff) — لا PHI في سجل التدقيق. عرض diff داخل الواجهة مؤجل (البيانات جاهزة).
- (م6) HL7: محوّل MDM مصغّر (MSH/EVN/PID/TXA/OBX) + MLLP client كمحرك INTEGRATION_ENGINE=hl7 — mllp://host:port في integration_configs. أول نقل T02 والاستبدال T09 بمرجع TXA-13 للوثيقة السابقة حصراً. اختُبر ضد خادم MLLP خيطي حقيقي.
- (م6) بذر الزيارات المنقولة لا ينشئ note_versions (لقطات النسخ تُبنى بالتدفق الحقيقي) — reopen على زيارة seed القديمة يرفض بوضوح حتى تمر بالدورة الفعلية.
- (م8) السياسات لكل منشأة (لا منصّية) — الأدمن يعدّل سياسات منشأته فقط، والافتراضات مضمّنة بالكود. retention_until المختوم على التسجيل هو الحاكم (السياسة تحكم الختم للجديد)؛ تغيير السياسة يسري على التسجيلات الجديدة — كما كان سلوك المنصة.
- (م8) خريطة الأنواع: intermediate_drafts = edit_events (كتابة/إملاء) + processing_attempts · ai_chat_logs = edit_events (قناة ai_chat) · transcript_raw يشمل diarization داخل صف transcripts نفسه. صفوف recordings لا تُحذف أبداً (الملف يُتلف والصف أثر) — REVOKE قائم.
- (م8) صمام medify.retention='purge' يسمح بالحذف الاحتفاظي فقط: على audit_logs في forbid_mutation المشترك (DELETE حصراً وعلى هذا الجدول حصراً) وعلى note_versions — دور التطبيق محجوب أصلاً بـ REVOKE فلا تغيير بوجهه. سقالة الاختبار للتقادم المفتعل: تعطيل مؤقت للـtrigger بدور المالك.
- (م10) التخزين JSONB مضمّن على `summary_sections.evidence_json` لا جدول `evidence_links` مستقل: السند يُقرأ دائماً مع قسمه، لا يُستعلم عبر الزيارات، وحجمه جُمَل معدودة — join إضافي على كل عرض مراجعة بلا مقابل. مشغّل الصوت عبر HTTP Range (لا signed URLs — التخزين محلي على القرص).
- (م11) درجة الثقة تُخزَّن داخل عنصر السند نفسه (لا عمود/جدول جديد) — الثقة صفة الجملة التي يقرؤها الطبيب. مع Gemini لا ثقة ASR فتغيب الدرجات ولا إبراز (تصميم يحتمل الغياب). العتبات منصّية لا لكل منشأة (اتساق الحكم السريري عبر المنصة).
- (م12) «لا يصلح تشخيصاً أولياً» يحجب فقط عند غياب تشخيص صالح آخر (الكود الممنوع ثانوياً مقبول) — وإلا لحجبنا مطالبات سليمة. الربط يُقبل من تشخيصات الزيارة المعتمدة حصراً (MDF-4233 خلاف ذلك). القواعد بلا حالة في القاعدة (ملفات فقط) — تعديلها لا يمس بيانات المستأجرين.
- (م12) أثر جانبي مقصود على الاختبارات: مساعدات «ارفض كل الإرشادات» كانت تنتج زيارة بلا تشخيص أولي فصارت تُحجب بـMDF-4237 — حُدِّثت لتقبل التشخيص كأي رحلة حقيقية (السلوك الجديد هو الصحيح سريرياً).
- (تشغيل) لا تُشغَّل حزمة pytest بالتوازي مع أمر آخر يلمس القاعدة — تصادم قاعدة الاختبار يُسقط اختبارات عشوائياً (تأكد عملياً في م12).

## BLOCKED

(لا شيء)

## ملاحظات جلسات متوازية

شجرة العمل عند بدء المرحلة 0 تحوي عملاً غير مودَع من جلسة موازية: هجرتا 0008 (void) و0010
(note-unlock) واختباراتهما + إصلاحات addendums (0009) + ‎+187 سطراً في شاشة المراجعة.
main المحلي متقدم على origin/main بـ3 إيداعات ومتأخر بواحد (8abc783 مطابق لـ dce14c2 محتوىً).
المعالجة المقترحة عند «نفّذ» مذكورة في خطة المرحلة 0.
