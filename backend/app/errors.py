"""رموز الأخطاء MDF — حصرياً الـ24 من DOC-13 v1.2 (22 + رمزا DOC-20 المعتمدين 2026-07-16).
لا يُخترع رمز هنا؛ يُضاف في الوثيقة أولاً."""
from __future__ import annotations

from typing import Any

# code: (http_status, message_ar, message_en)
MDF_CATALOG: dict[str, tuple[int, str, str]] = {
    # ١ — مصادقة وصلاحيات (40xx)
    "MDF-4011": (401, "بيانات الدخول غير صحيحة.", "Invalid credentials."),
    "MDF-4012": (401, "انتهت الجلسة — يلزم تسجيل الدخول من جديد.", "Session expired — please sign in again."),
    "MDF-4031": (403, "هذا الإجراء خارج صلاحيات دورك.", "Action outside your role permissions."),
    "MDF-4041": (404, "المورد غير موجود أو خارج نطاق رؤيتك.", "Resource not found or outside your visibility scope."),
    "MDF-4013": (403, "الحساب معطّل أو المنشأة معلّقة — تواصل مع الأدمن أو سدد الفواتير المستحقة.", "Account disabled or facility suspended — contact your admin or settle due invoices."),
    "MDF-4014": (401, "رابط استعادة كلمة المرور غير صالح أو منتهٍ أو مستخدم.", "Password reset link is invalid, expired, or already used."),
    "MDF-4015": (401, "المصادقة الثنائية مطلوبة أو الرمز غير صحيح.", "Two-factor authentication required or the code is incorrect."),
    # ٢ — قواعد العمل (42xx)
    "MDF-4221": (422, "لا مقاعد متاحة — وسّع الاشتراك أولاً.", "No seats available — expand the subscription first."),
    "MDF-4222": (422, "لا يمكن الاعتماد — توجد إرشادات معلقة يجب حسمها أولاً.", "Approval blocked — pending guidance items must be resolved first."),
    "MDF-4223": (409, "انتقال حالة الزيارة غير مسموح.", "Visit state transition not allowed."),
    "MDF-4224": (412, "تعارض تحرير — عُدّلت النسخة من جلسة أخرى.", "Edit conflict — a newer version exists (ETag mismatch)."),
    "MDF-4225": (422, "القالب غير صالح للحفظ — البنية ناقصة.", "Template invalid for saving — structure incomplete."),
    "MDF-4226": (422, "لا يمكن تعديل زيارة معتمدة.", "Approved visits cannot be modified."),
    "MDF-4227": (422, "الإلغاء غير مسموح — الزيارة تجاوزت مرحلة التسجيل.", "Cancellation not allowed — visit is past the recording stage."),
    "MDF-4228": (422, "فشلت عملية السداد لدى مزود الدفع.", "Payment failed at the payment provider."),
    "MDF-4229": (422, "لا يمكن تعطيل أو تخفيض آخر حساب مالك فعّال للمنصة.", "The last active platform owner account cannot be disabled or downgraded."),
    "MDF-4291": (429, "تجاوزت حد المعدل — أعد المحاولة بعد قليل.", "Rate limit exceeded — retry shortly."),
    # ٣ — المعالجة والتكامل (50xx)
    "MDF-5031": (500, "انقطاع خط التفريغ الفوري.", "Live transcription pipeline interrupted."),
    "MDF-5032": (500, "فشل توليد الملخص بعد إعادة المحاولة.", "Summary generation failed after retry."),
    "MDF-5033": (500, "فشل توليد الإرشاد المدمج — الملخص متاح بلا إرشادات.", "Inline guidance failed — summary available without guidance."),
    "MDF-5034": (500, "فشل البناء العكسي أو محادثة التعديل — أعد المحاولة.", "Reverse template build or edit chat failed — retry."),
    "MDF-5051": (502, "رفض نظام المستشفى حزمة الرفع (خطأ تحقق بنيوي).", "Hospital system rejected the upload bundle (validation error)."),
    "MDF-5052": (504, "تعذّر الوصول إلى نظام المستشفى.", "Hospital system unreachable."),
    "MDF-5001": (500, "خطأ داخلي غير مصنّف.", "Unclassified internal error."),
}

assert len(MDF_CATALOG) == 24, "DOC-13 v1.2: 24 رمزاً لا غير (22 + MDF-4015/4229 من DOC-20)"


class MedifyError(Exception):
    """خطأ عمل مرقّم — يُغلَّف وفق DOC-05 §١."""

    def __init__(self, code: str, details: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
        if code not in MDF_CATALOG:
            raise ValueError(f"رمز غير معرف في DOC-13: {code}")
        self.code = code
        self.http_status, self.message_ar, self.message_en = MDF_CATALOG[code]
        self.details = details or {}
        self.headers = headers or {}
        super().__init__(f"{code}: {self.message_en}")

    def body(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message_ar": self.message_ar,
                "message_en": self.message_en,
                "details": self.details,
            }
        }
