import { expect, test } from "@playwright/test";

/** حفظ اسم المنشأة واسم المستخدم تلقائياً بعد دخول ناجح (طلب مالك 2026-07-15). */

test("facility and username are remembered after successful login", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("medify_lang", "ar"));
  await page.goto("/login");
  await page.getByPlaceholder("اسم المنشأة أو السجل التجاري").fill("1010456789");
  await page.getByPlaceholder("dr.username").fill("dr.ahmad");
  await page.getByPlaceholder("••••••••").fill(process.env.E2E_DOCTOR_PASSWORD ?? "Doctor@12345");
  await page.getByRole("button", { name: "دخول" }).click();
  await page.waitForURL("**/doctor");

  // العودة لصفحة الدخول: المنشأة والمستخدم معبآن مسبقاً — كلمة المرور لا تُحفظ
  await page.goto("/login");
  await expect(page.getByPlaceholder("اسم المنشأة أو السجل التجاري")).toHaveValue("1010456789");
  await expect(page.getByPlaceholder("dr.username")).toHaveValue("dr.ahmad");
  await expect(page.getByPlaceholder("••••••••")).toHaveValue("");
});
