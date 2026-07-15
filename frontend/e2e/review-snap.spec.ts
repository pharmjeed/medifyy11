import { test } from "@playwright/test";

/** لقطة موجهة للصفحة المحورية (15) — تعمل بـ E2E_SNAPSHOTS=1 فقط. */
test.skip(process.env.E2E_SNAPSHOTS !== "1", "snapshots only on demand");

const OUT = process.env.SNAP_DIR ?? "test-results/snaps";

test("review page snapshot", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("medify_lang", "ar"));
  await page.setViewportSize({ width: 1440, height: 1200 });
  await page.goto("/login");
  await page.getByPlaceholder("اسم المنشأة أو السجل التجاري").fill("1010456789");
  await page.getByPlaceholder("dr.username").fill("dr.ahmad");
  await page.getByPlaceholder("••••••••").fill(process.env.E2E_DOCTOR_PASSWORD ?? "Doctor@12345");
  await page.getByRole("button", { name: "دخول" }).click();
  await page.waitForURL("**/doctor");

  await page.goto("/doctor/visits");
  await page.waitForTimeout(1500);
  await page.getByRole("link", { name: "فتح المراجعة" }).first().click();
  await page.waitForURL("**/review");
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/15b-review-top.png` });
  await page.screenshot({ path: `${OUT}/15c-review-full.png`, fullPage: true });
});
