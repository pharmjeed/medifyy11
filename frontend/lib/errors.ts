/** رموز MDF الـ22 (DOC-13 v1.1) — رسالة وإجراء مقترح بالعربية والإنجليزية لسلوك W-004. */

export interface MdfMeta {
  message_ar: string;
  message_en: string;
  action_ar: string;
  action_en: string;
}

export const MDF_UI: Record<string, MdfMeta> = {
  "MDF-4011": {
    message_ar: "بيانات الدخول غير صحيحة.", message_en: "Invalid sign-in credentials.",
    action_ar: "تحقق من اسم المنشأة والمستخدم وكلمة المرور — الرسالة عامة عمداً.",
    action_en: "Check the facility, username and password — this message is intentionally generic.",
  },
  "MDF-4012": {
    message_ar: "انتهت الجلسة.", message_en: "Your session has expired.",
    action_ar: "سيُعاد توجيهك لتسجيل الدخول بعد محاولة تجديد صامت.",
    action_en: "You will be redirected to sign in after a silent refresh attempt.",
  },
  "MDF-4031": {
    message_ar: "هذا الإجراء خارج صلاحيات دورك.", message_en: "This action is outside your role permissions.",
    action_ar: "راجع مصفوفة الصلاحيات مع أدمن المنشأة.",
    action_en: "Review the permission matrix with your facility admin.",
  },
  "MDF-4041": {
    message_ar: "المورد غير موجود أو خارج نطاق رؤيتك.", message_en: "Resource not found or outside your visibility scope.",
    action_ar: "تأكد من الرابط أو عد للصفحة السابقة.",
    action_en: "Check the link or go back to the previous page.",
  },
  "MDF-4013": {
    message_ar: "الحساب معطّل أو المنشأة معلّقة.", message_en: "Account disabled or facility suspended.",
    action_ar: "تواصل مع أدمن المنشأة — وللأدمن: سدد الفواتير المستحقة.",
    action_en: "Contact your facility admin — admins: settle the outstanding invoices.",
  },
  "MDF-4014": {
    message_ar: "رابط الاستعادة غير صالح أو منتهٍ أو مستخدم.", message_en: "Reset link is invalid, expired, or already used.",
    action_ar: "اطلب رابط استعادة جديداً.", action_en: "Request a new reset link.",
  },
  "MDF-4221": {
    message_ar: "لا مقاعد متاحة.", message_en: "No seats available.",
    action_ar: "وسّع المقاعد من صفحة المقاعد والفوترة أو عطّل حساباً.",
    action_en: "Expand seats from Seats & Billing, or deactivate an account.",
  },
  "MDF-4222": {
    message_ar: "توجد إرشادات معلقة.", message_en: "There are pending guidance items.",
    action_ar: "احسم كل الإرشادات (قبول/رفض/تعديل) قبل الاعتماد.",
    action_en: "Resolve every guidance item (accept/reject/modify) before approval.",
  },
  "MDF-4223": {
    message_ar: "انتقال حالة غير مسموح.", message_en: "Visit state transition not allowed.",
    action_ar: "حُدّثت الشاشة للحالة الفعلية للزيارة.", action_en: "The screen was refreshed to the visit's actual state.",
  },
  "MDF-4224": {
    message_ar: "تعارض تحرير — نسخة أحدث موجودة.", message_en: "Edit conflict — a newer version exists.",
    action_ar: "راجع النسختين واختر إحداهما (W-222).", action_en: "Compare both versions and choose one (W-222).",
  },
  "MDF-4225": {
    message_ar: "بنية القالب ناقصة.", message_en: "Template structure is incomplete.",
    action_ar: "أكمل الأقسام الناقصة في المعاينة ثم احفظ.", action_en: "Complete the missing sections in the preview, then save.",
  },
  "MDF-4226": {
    message_ar: "الزيارة معتمدة — لا تعديل.", message_en: "Visit is approved — no further edits.",
    action_ar: "تُعرض الزيارة للقراءة فقط.", action_en: "The visit is shown read-only.",
  },
  "MDF-4227": {
    message_ar: "الإلغاء غير متاح بعد التسجيل.", message_en: "Cancellation is unavailable after recording.",
    action_ar: "أكمل المراجعة أو اعتمد الزيارة.", action_en: "Complete the review or approve the visit.",
  },
  "MDF-4228": {
    message_ar: "فشلت عملية السداد.", message_en: "Payment failed.",
    action_ar: "أعد المحاولة أو جرّب وسيلة دفع أخرى.", action_en: "Retry or try another payment method.",
  },
  "MDF-4291": {
    message_ar: "تجاوزت حد المعدل.", message_en: "Rate limit exceeded.",
    action_ar: "انتظر قليلاً — ستُعاد المحاولة تلقائياً.", action_en: "Wait a moment — it will retry automatically.",
  },
  "MDF-5031": {
    message_ar: "انقطاع خط التفريغ الفوري.", message_en: "Live transcription pipeline interrupted.",
    action_ar: "تحوّلت الجلسة لوضع الحفظ المحلي وستُستأنف تلقائياً (W-223).",
    action_en: "Switched to local-save mode; it will resume automatically (W-223).",
  },
  "MDF-5032": {
    message_ar: "فشل توليد الملخص.", message_en: "Summary generation failed.",
    action_ar: "أعد التوليد يدوياً — الصوت والتفريغ محفوظان.",
    action_en: "Regenerate manually — the audio and transcript are preserved.",
  },
  "MDF-5033": {
    message_ar: "فشل التحليل الذكي.", message_en: "AI analysis failed.",
    action_ar: "الملخص متاح بلا إرشادات — يمكن إعادة التحليل (W-224).",
    action_en: "The summary is available without guidance — analysis can be retried (W-224).",
  },
  "MDF-5034": {
    message_ar: "فشل البناء العكسي / محادثة التعديل.", message_en: "Reverse template build / edit chat failed.",
    action_ar: "أعد المحاولة من الشاشة نفسها.", action_en: "Retry from the same screen.",
  },
  "MDF-5051": {
    message_ar: "رفض نظام المستشفى الحزمة.", message_en: "The hospital system rejected the bundle.",
    action_ar: "راجع تفاصيل الرفض الفنية مع الأدمن (W-219).",
    action_en: "Review the technical rejection details with your admin (W-219).",
  },
  "MDF-5052": {
    message_ar: "تعذر الوصول لنظام المستشفى.", message_en: "Hospital system is unreachable.",
    action_ar: "إعادة المحاولة آلية — الأدمن أُشعر بذلك.",
    action_en: "Retries are automatic — the admin has been notified.",
  },
  "MDF-5001": {
    message_ar: "خطأ داخلي غير مصنف.", message_en: "Unclassified internal error.",
    action_ar: "أعد المحاولة، وإن تكرر فتواصل مع الدعم بمعرف التتبع.",
    action_en: "Retry; if it persists, contact support with the trace ID.",
  },
};

export function mdfMeta(code: string, lang: "ar" | "en" = "ar"): { message_ar: string; action: string } {
  const meta = MDF_UI[code] ?? MDF_UI["MDF-5001"]!;
  return { message_ar: lang === "ar" ? meta.message_ar : meta.message_en, action: lang === "ar" ? meta.action_ar : meta.action_en };
}
