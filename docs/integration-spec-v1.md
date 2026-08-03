# مواصفة التكامل v1 — ملحق دلالة الاستبدال وIdempotency

**علاقتها بـ`docs/manara/B2-integration-spec-v1.html`:** تلك الوثيقة تصف الحزمة
الأساسية وقنواتها ونطاق العمل. هذه تُكمل ما لم يكن مبنياً حين كُتبت: **دلالة
الاستبدال بين النسخ**، و**Idempotency**، و**المريض الخطأ بعد النقل**. كل ما هنا
منفَّذ فعلاً — الأمثلة مولَّدة من الكود لا مقترحة.

المراجع في الكود: `services/fhir.py` · `services/hl7.py` · `services/uploader.py` ·
`services/versions.py` · هجرتا `0014` و`0015`.

---

## 1) دلالة الاستبدال (Replacement Semantics)

### 1.1 القاعدة

كل مذكرة تُنقل بوصفها **نسخة مرقّمة** من الزيارة. النسخة الأولى وثيقة أصلية؛ وكل
نسخة لاحقة (بعد `reopen`) **تستبدل سابقتها من Medify حصراً**.

معرّف وثيقة Medify الثابت — أساس كل إشارة استبدال:

```
urn:medify:doc:{visit_id}:{version_number}
```

مشتق من (الزيارة، رقم النسخة) فقط — لا من التاريخ ولا من نوع الوثيقة ولا من
المريض. (`services/fhir.py: medify_doc_identifier`)

### 1.2 FHIR R4

النسخة **1** — `Composition.status = "final"`، و`DocumentReference` بلا `relatesTo`:

```json
{
  "resourceType": "Composition",
  "id": "composition-{visit_id}-v1",
  "status": "final",
  "type": {"coding": [{"system": "http://loinc.org", "code": "11488-4",
                       "display": "Consult note"}]},
  "title": "Medify SOAP Summary",
  "section": [{"title": "S", "text": {"status": "generated", "div": "<div …>…</div>"}}]
}
```

النسخة **≥2** — `amended` + إشارة الاستبدال المباشرة:

```json
{
  "resourceType": "Composition",
  "id": "composition-{visit_id}-v2",
  "status": "amended"
}
```

```json
{
  "resourceType": "DocumentReference",
  "id": "docref-{visit_id}-v2",
  "status": "current",
  "masterIdentifier": {"system": "urn:medify:doc",
                       "value": "urn:medify:doc:{visit_id}:2"},
  "type": {"coding": [{"system": "http://loinc.org", "code": "11488-4"}]},
  "subject": {"reference": "Patient/{hospital_mrn}"},
  "content": [{"attachment": {"contentType": "application/fhir+json",
                              "title": "Medify SOAP Summary v2"}}],
  "context": {"encounter": [{"reference": "Encounter/encounter-{visit_id}"}]},
  "relatesTo": [{
    "code": "replaces",
    "target": {"identifier": {"system": "urn:medify:doc",
                              "value": "urn:medify:doc:{visit_id}:1"}}
  }]
}
```

كل مدخل في الحزمة يحمل `request` صالحاً (نوع `transaction`) مع `ifNoneExist`:

```json
{
  "resource": { "resourceType": "DocumentReference", "...": "..." },
  "request": {
    "method": "POST",
    "url": "DocumentReference",
    "ifNoneExist": "identifier=urn:medify:doc|urn:medify:doc:{visit_id}:2"
  }
}
```

### 1.3 HL7 v2 (`INTEGRATION_ENGINE=hl7`)

| الحدث | الرسالة | الدلالة |
|---|---|---|
| أول نقل لنسخة الزيارة | `MDM^T02` | وثيقة أصلية |
| نسخة ≥2 بعد `reopen` | `MDM^T09` | استبدال الوثيقة الأم |
| (اختياري لدى المستقبِل) | `MDM^T10` | استبدال بمحتوى بديل |

مثال حقيقي من المحوّل (`services/hl7.py`) — الاستبدال:

```
MSH|^~\&|MEDIFY|MEDIFY|HIS|HIS|20260803034512||MDM^T09|{visit_id}:2|P|2.5
EVN|T09|20260803034512
PID|1||1042376||محمد عبدالله القحطاني
TXA|1|CN|TX|20260803034512|د. نورة العتيبي||||||urn:medify:doc:{visit_id}:2|urn:medify:doc:{visit_id}:1|||AU
OBX|1|TX|NOTE||[S] Patient reports…
OBX|2|TX|NOTE||[A] Uncontrolled hypertension…
```

- **TXA-12** = معرّف وثيقة هذه النسخة.
- **TXA-13** = معرّف الوثيقة الأم — الوثيقة المستهدفة بالاستبدال.
- **TXA-17** = `AU` (authenticated) — لا تُرسل مذكرة لم تجتز البوابتين.
- **MSH-10** = مفتاح Idempotency (§2).
- النقل: MLLP فوق TLS (`mllp://host:port`)، والنجاح = `MSA|AA` أو `MSA|CA`.

### 1.4 قاعدة عدم التصادم

> النسخة الجديدة تستبدل **وثيقة Medify السابقة حصراً** بالمرجع المباشر.

- محتوى Medify يُحرَّر في Medify فقط (بند العقد 2).
- ما يضيفه موظفو المستشفى (تقارير، ملاحظات تمريض، وثائق أخرى) **وثائق مستقلة**
  لا يطالها استبدال Medify — لأن الإشارة بمعرّف وثيقة بعينه لا بالنوع ولا بالزيارة.
- استبدال متسلسل: v3 يستبدل v2 (لا v1) — سلسلة قابلة للتتبع كاملة.

### 1.5 التزام نظام المستشفى

الاستبدال **إضافة لا محو**: تبقى النسخة السابقة قابلة للاسترجاع موسومةً بأنها
استُبدلت. Medify لا يطلب حذف شيء من سجل المريض ولا يملك صلاحيته.

---

## 2) Idempotency

### 2.1 المفتاح

```
idempotency_key = "{visit_id}:{version_number}"
```

- عمود فريد على `upload_jobs` — لا مهمتا رفع بنفس المفتاح (هجرة `0015`).
- **إعادة المحاولة** (`retry-upload`) تحمل المفتاح **نفسه** — عملية واحدة منطقياً.
- **النسخة الجديدة** (`reopen` → v+1) مفتاح **جديد** — عملية مستقلة.

### 2.2 الدفاع بثلاث طبقات

| الطبقة | الآلية | تحمي من |
|---|---|---|
| قاعدة Medify | قيد فريد على `idempotency_key` | إنشاء مهمتي رفع لنفس النسخة |
| إيصالات التسليم | `delivery_receipts (idempotency_key, target_system)` فريد | إعادة الإرسال بعد تسليم ناجح ضاع ردّه |
| الطرف البعيد | `ifNoneExist` (FHIR) · `MSH-10` (HL7) | ازدواج الكتابة إن وصل الإرسال مرتين |

### 2.3 دورة الإيصال

1. **قبل أي إرسال**: يُفحص وجود إيصال لهذا (المفتاح، الوجهة). موجود → يُرجَع
   النجاح السابق **بلا إرسال**، وتُختم المهمة والنسخة والحالة، ويُدوَّن في
   التدقيق بعلامة `replayed_from_receipt`.
2. **فور الاستقبال الناجح**: يُكتب الإيصال في **جلسة قاعدة مستقلة** (commit فوري)
   **قبل** أي تحديث حالة — فانهيار الخادم بعد التسليم لا يسبب إرسالاً ثانياً.
3. الإيصال يحمل بصمة رد النظام المستقبِل (`response_hash`) — لا محتواه.

```sql
-- بنية الإيصال
idempotency_key   text     -- "{visit_id}:{version}"
target_system     text     -- mock | http | hl7
delivered_at      timestamptz
response_hash     text     -- sha256 لرد الوجهة (بلا محتوى)
```

### 2.4 ما يجب على النظام المستقبِل

- احترام `ifNoneExist` في مدخلات الحزمة (سلوك FHIR R4 القياسي)، أو
- رفض/تجاهل رسالة بـ`MSH-10` سبق استقبالها (سلوك HL7 v2 القياسي).

بدون ذلك، تبقى طبقتا Medify فعّالتين لكن الحالة النادرة «وصل الإرسال وضاع الرد
قبل كتابة الإيصال» قد تُنتج كتابة مكررة — يزيلها المفتاح الثابت لدى المستقبِل.

---

## 3) مريض خطأ بعد النقل

اكتُشف بعد نقل المذكرة أنها سُجّلت على ملف مريض خطأ. **قبل** النقل المسار هو
الإبطال (`void`)؛ بعده الحالة تتطلب تدخل المستشفى.

### 3.1 ما يفعله Medify

1. يوفّر معرّف الوثيقة الدقيق `urn:medify:doc:{visit_id}:{version}` ووقت النقل
   وبصمة الحزمة (`note_versions.bundle_hash`).
2. يُدوّن البلاغ في سجل التدقيق الإلحاقي.
3. **لا يحذف** شيئاً من سجل المستشفى — ولا يملك صلاحيته (بند العقد 1).
4. الزيارة الصحيحة تُنشأ من جديد على المريض الصحيح وتمر بدورتها كاملة.

### 3.2 ما يفعله نظام المستشفى

**المسار المفضّل — FHIR:** تعليم الوثيقة `entered-in-error`:

```json
{"resourceType": "DocumentReference", "id": "docref-{visit_id}-v1",
 "status": "entered-in-error"}
```

```json
{"resourceType": "Composition", "id": "composition-{visit_id}-v1",
 "status": "entered-in-error"}
```

**المسار البديل — HL7 v2:** `MDM^T11` (Document cancel notification) إن كان
مدعوماً لدى المستقبِل، بـ`TXA-12` يحمل معرّف الوثيقة المستهدفة.

### 3.3 إن لم يدعم النظام أياً منهما — الإجراء اليدوي الموثّق

1. **البلاغ**: مسؤول التكامل يفتح تذكرة لقسم **إدارة المعلومات الصحية (HIM)**
   خلال يوم عمل واحد، مرفقةً بمعرّف الوثيقة ووقت النقل ورقم ملف المريض المتأثر.
2. **الإجراء**: HIM ينفّذ إجراء «مُدخل بالخطأ» المعتمد لديه: إخفاء الوثيقة من
   العرض السريري مع **إبقائها في الأرشيف التدقيقي** موسومةً بسببها ومنفّذها.
3. **التوثيق**: يوقّع على الإجراء مسؤول HIM + الطبيب صاحب المذكرة، ويُحفظ
   المستند في سجل الحوادث لدى المنشأة.
4. **التأكيد**: يبلّغ HIM فريق Medify بإتمام الإجراء لإغلاق التذكرة.
5. **المنع**: يُراجَع سبب الخطأ (اختيار مريض خاطئ في شاشة الزيارة) ضمن مراجعة
   الجودة الدورية.

> **لا يجوز** حلّ الحالة بـ`reopen` — إعادة الفتح تنتج نسخة **على المريض نفسه**
> وتستبدل السابقة، ولا تنقل شيئاً إلى ملف المريض الصحيح ولا تُخرج الخطأ من الملف الخاطئ.

---

## 4) خلاصة الفروق عن B2

| الموضوع | B2 v1.0 | هذه الوثيقة |
|---|---|---|
| `entry.request` في الحزمة | غير مذكور (وكان مفقوداً في التنفيذ) | مبنيّ وإلزامي مع `ifNoneExist` |
| `DocumentReference` | غير موجود في الحزمة | مبنيّ بمعرّف ثابت |
| دلالة الاستبدال | غائبة | `amended` + `relatesTo/replaces` · `MDM T02/T09` |
| Idempotency | غائبة | مفتاح واعٍ بالنسخة + إيصالات + دفاع الطرف البعيد |
| مريض خطأ بعد النقل | غائب | `entered-in-error` / `T11` / إجراء HIM يدوي موثّق |
| HL7 v2 | «يُبنى عند الاعتماد» | محوّل MDM + عميل MLLP مبنيّان ومختبَران |
