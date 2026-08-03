# قواعد جاهزية المطالبة (Claim-Readiness) — بيانات لا كود

كل ملف `.yaml` هنا يحمل قواعد من نوع واحد. المحرك
(`app/services/claim_readiness.py`) يقرأها ويقيّمها بلا أي منطق خاص بقاعدة بعينها —
**إضافة قاعدة جديدة لا تتطلب نشر كود**، فقط ملف أو إدخال جديد.

## البنية العامة لكل قاعدة

```yaml
- rule_id: MEDICAL_NECESSITY_LINK      # فريد عبر كل الملفات
  type: medical_necessity | mds_completeness | code_composition | prior_auth
  severity: block | warn | pass        # block يعطّل زر الاعتماد
  message_ar: "رسالة عربية تُعرض للطبيب"
  enabled: true                        # اختياري (افتراضي true)
  params: { ... }                      # حسب النوع
```

## الأنواع الأربعة وبارامتراتها

### 1) `medical_necessity` — ربط الضرورة الطبية
كل كود غير تشخيصي (إجراء/خدمة/دواء/جهاز) يجب أن يرتبط بتشخيص ICD-10-AM.

```yaml
params:
  requires_link_for_kinds: [clinical_procedure, clinical_service, clinical_rx, clinical_device]
  diagnosis_kinds: [clinical_dx, coding_match]     # ما يُعدّ تشخيصاً مبرِّراً
  diagnosis_system: ICD10AM
```

### 2) `mds_completeness` — اكتمال حقول NPHIES الإلزامية

```yaml
params:
  required_fields:                      # اسم الحقل: مسار قراءته من سياق الزيارة
    - field: patient_mrn
      message_ar: "رقم ملف المريض (MRN) غير متوفر"
    - field: encounter_date
      message_ar: "تاريخ الزيارة غير متوفر"
```

الحقول المدعومة (يوفّرها المحرك من الزيارة): `patient_mrn` · `patient_dob` ·
`patient_gender` · `encounter_date` · `clinic` · `physician_name` ·
`primary_diagnosis` · `payer`.

### 3) `code_composition` — تركيب الأكواد

```yaml
params:
  not_primary_diagnosis: [Z00.0, R51]          # لا يصلح تشخيصاً أولياً
  manifestation_requires:                       # كود مظهري يتطلب الحالة الأساسية
    - code: H36.0
      requires_any: [E10, E11]
      message_ar: "اعتلال الشبكية السكري يتطلب توثيق نوع السكري"
  conflicting_pairs:                            # زوجان لا يجتمعان
    - pair: [Z00.0, I10]
      message_ar: "فحص دوري سليم لا يجتمع مع تشخيص نشط"
```

### 4) `prior_auth` — أعلام التفويض المسبق (تحذير دائماً)

```yaml
params:
  codes: [73000-00-60]
  code_prefixes: ["9019"]
```

## الفحص

يعمل تلقائياً عند دخول البوابة ② وبعد كل تغيير أكواد
(`GET /api/v1/visits/{id}/claim-readiness`)، ويُعاد على كل نسخة (م6).
أي `block` غير محسوم يمنع الاعتماد بكود **MDF-4237**.
