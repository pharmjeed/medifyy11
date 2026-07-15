import { expect, test } from "@playwright/test";

/** الرحلة الكاملة E2E بالـ mocks (معيار القبول الثالث):
 *  دخول دكتور → اختيار مريض (من المزامنة) → قالب → تسجيل + تفريغ متدفق →
 *  ملخص → إرشادات مضمّنة → حسم → اعتماد → رفع (وهمي) → السجل. */

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

  // 4) اختيار القالب (W-211) — الافتراضي محدد مسبقاً
  await expect(page.getByText("اختيار قالب التلخيص")).toBeVisible();
  await page.getByRole("button", { name: /بدء التسجيل/ }).click();

  // 5) التسجيل الحي + التفريغ المتدفق (W-212)
  await expect(page.getByText("متصل")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("يشتكي المريض من").or(page.getByText("السلام عليكم دكتور"))).toBeVisible({ timeout: 20_000 });
  // كل مقطع يحمل هوية متكلمه المُستنتَجة — أول أدوار الحوار للمريض
  await expect(page.getByText("المريض", { exact: true }).first()).toBeVisible({ timeout: 20_000 });

  // 6) إنهاء → حالة التوليد (W-213) → المراجعة
  await page.getByRole("button", { name: "إنهاء التسجيل وتوليد الملخص" }).click();
  await page.waitForURL("**/review", { timeout: 60_000 });

  // 7) مساحة المراجعة (W-214): أقسام من القالب ديناميكياً + إرشادات مضمّنة بمصدرها
  await expect(page.getByText("Subjective")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Patient education")).toBeVisible(); // القسم E — 5 أقسام لا SOAP مثبتة
  await expect(page.getByText("المصدر:").first()).toBeVisible();

  // 8) زر الاعتماد معطّل مع إرشادات معلقة (W-218 / MDF-4222)
  const approveButton = page.getByRole("button", { name: "اعتمد وارفع" });
  await expect(approveButton).toBeDisabled();

  // 9) حسم كل الإرشادات المعلقة (قبول)
  const acceptButtons = page.getByRole("button", { name: "قبول", exact: true });
  while ((await acceptButtons.count()) > 0) {
    await acceptButtons.first().click();
    await page.waitForTimeout(400);
  }
  await expect(page.getByText("صفر إرشادات معلقة — جاهزة للاعتماد", { exact: false })).toBeVisible({ timeout: 10_000 });

  // 10) اعتماد → رفع وهمي ناجح (W-219)
  await expect(approveButton).toBeEnabled();
  await approveButton.click();
  await expect(page.getByText("رفع ناجح ✓", { exact: false })).toBeVisible({ timeout: 30_000 });

  // 11) الزيارة في السجل بحالة «مرفوعة ✓» (W-202)
  await page.getByRole("button", { name: "سجل الزيارات" }).click();
  await page.waitForURL("**/doctor/visits");
  await expect(page.getByText("مرفوعة ✓").first()).toBeVisible({ timeout: 15_000 });
});
