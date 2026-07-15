import { expect, test } from "@playwright/test";

/** اللغة: الإنجليزية افتراضياً (D-30) + التبديل للعربية يقلب الاتجاه والنصوص ويبقى محفوظاً. */

test("English is the default and toggle switches to Arabic", async ({ page }) => {
  await page.goto("/login");

  // الافتراضي: إنجليزي LTR
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

  // التبديل للعربية
  await page.getByRole("button", { name: "التبديل إلى العربية" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "تسجيل الدخول" })).toBeVisible();

  // الاختيار محفوظ بعد التحديث
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "تسجيل الدخول" })).toBeVisible();

  // والعودة للإنجليزية
  await page.getByRole("button", { name: "Switch to English" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});
