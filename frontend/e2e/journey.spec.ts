import { expect, test } from "@playwright/test";

/** الرحلة الكاملة E2E بالـ mocks (معيار القبول الثالث):
 *  دخول دكتور → اختيار مريض (من المزامنة) → قالب → موافقة → تسجيل (صوت فقط —
 *  لا تفريغ أثناء المحادثة، قرار مالك 2026-08-02) → إنهاء: تفريغ كامل + ملخص →
 *  إرشادات مضمّنة → حسم → اعتماد → رفع (وهمي) → السجل. */

test("الرحلة الكاملة: من الدخول إلى الرفع", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("medify_lang", "ar")); // النصوص المؤكدة عربية
  // 1) الدخول (W-001)
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "تسجيل الدخول" })).toBeVisible();
  await page.getByPlaceholder("اسم المنشأة أو السجل التجاري").fill("1010456789");
  await page.getByPlaceholder("dr.username").fill("dr.ahmad");
  await page.getByPlaceholder("••••••••").fill(process.env.E2E_DOCTOR_PASSWORD ?? "Doctor@12345");
  await page.getByRole("button", { name: "دخول" }).click();

  // 2) رئيسة الدكتور (W-201)
  await page.waitForURL("**/doctor");
  await expect(page.getByText("رئيسة الدكتور").first()).toBeVisible();

  // 3) بدء زيارة — اختيار المريض (W-210)
  await page.goto("/doctor/visits/new");
  await page.getByPlaceholder("ابحث بالاسم أو رقم الملف MRN…").fill("منيرة");
  await page.getByText("منيرة سعد الدوسري").first().click();
  await expect(page.getByText("موجز ملف المريض")).toBeVisible();
  await page.getByRole("button", { name: "التالي: اختيار القالب" }).click();

  // 4) اختيار القالب (W-211) — الافتراضي محدد مسبقاً → بوابة الموافقة (A1)
  await expect(page.getByText("اختيار قالب التلخيص")).toBeVisible();
  await page.getByRole("button", { name: "التالي — موافقة المريض" }).click();

  // 5) توثيق موافقة المريض ثم التسجيل (W-212) — صوت فقط: لا نص يظهر أثناء المحادثة
  await expect(page.getByText("موافقة المريض على التسجيل")).toBeVisible();
  await page.locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "وثّق الموافقة وابدأ التسجيل" }).click();
  await expect(page.getByText("متصل")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("التفريغ بعد إنهاء المحادثة")).toBeVisible();

  // 6) إنهاء → التوليد (W-213: تفريغ المحادثة كاملة → ملخص → تحليل) → المراجعة
  await page.waitForTimeout(1500); // يتجمّع صوت الجهاز الوهمي قبل الإنهاء
  await page.getByRole("button", { name: "إنهاء التسجيل وتوليد الملخص" }).click();
  await page.waitForURL("**/review", { timeout: 60_000 });

  // 7) مساحة المراجعة (W-214): أقسام من القالب ديناميكياً + إرشادات مضمّنة بمصدرها
  await expect(page.getByText("Subjective")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Patient education")).toBeVisible(); // القسم E — 5 أقسام لا SOAP مثبتة
  await expect(page.getByText("المصدر:").first()).toBeVisible();

  // 8) البوابة ① — اعتماد نص المذكرة (يجمّد النص ويفتح حسم الأكواد)
  await page.getByRole("button", { name: "① اعتماد نص المذكرة" }).click();
  const approveCodesButton = page.getByRole("button", { name: "② اعتماد الأكواد والرفع" });
  await expect(approveCodesButton).toBeVisible({ timeout: 10_000 });
  await expect(approveCodesButton).toBeDisabled(); // إرشادات معلقة (MDF-4222)

  // 9أ) البند المحجوب دون العتبة («لا تخمين») — يُحسم بإدخال الكود يدوياً عبر «تعديل»
  const withheldCard = page.locator("div")
    .filter({ has: page.getByText("«لا تخمين»") })
    .filter({ has: page.getByRole("button", { name: "تعديل" }) })
    .last();
  await withheldCard.getByRole("button", { name: "تعديل" }).click();
  await withheldCard.locator("input.mono").fill("G44");
  await withheldCard.getByRole("button", { name: /G44\.2/ }).first().click(); // إكمال من السجل المرجعي
  await withheldCard.getByRole("button", { name: "حفظ وقبول معدلاً" }).click();

  // 9ب) حسم بقية الإرشادات المعلقة (قبول)
  const acceptButtons = page.getByRole("button", { name: "قبول", exact: true });
  while ((await acceptButtons.count()) > 0) {
    await acceptButtons.first().click();
    await page.waitForTimeout(400);
  }
  await expect(page.getByText("جاهزة لاعتماد الأكواد", { exact: false })).toBeVisible({ timeout: 10_000 });

  // 10) البوابة ② — اعتماد الأكواد → رفع وهمي ناجح (W-219)
  await expect(approveCodesButton).toBeEnabled();
  await approveCodesButton.click();
  await expect(page.getByText("رفع ناجح ✓", { exact: false })).toBeVisible({ timeout: 30_000 });

  // 11) الزيارة في السجل بحالة «مرفوعة ✓» (W-202)
  await page.getByRole("button", { name: "سجل الزيارات" }).click();
  await page.waitForURL("**/doctor/visits");
  await expect(page.getByText("مرفوعة ✓").first()).toBeVisible({ timeout: 15_000 });
});
