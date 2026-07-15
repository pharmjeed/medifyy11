import { test } from "@playwright/test";

/** أداة تخطيط: لقطات للفحص البصري — ليست اختباراً وظيفياً (تعمل بـ E2E_SNAPSHOTS=1). */

const OUT = process.env.SNAP_DIR ?? "test-results/snaps";

test.skip(process.env.E2E_SNAPSHOTS !== "1", "snapshots only on demand");

async function login(page: import("@playwright/test").Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByPlaceholder("اسم المنشأة أو السجل التجاري").fill("1010456789");
  await page.getByPlaceholder("dr.username").fill(username);
  await page.getByPlaceholder("••••••••").fill(password);
  await page.getByRole("button", { name: "دخول" }).click();
  await page.waitForTimeout(1500);
}

test("snapshots", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("medify_lang", "ar"));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/login");
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/01-login.png` });

  await login(page, "dr.ahmad", process.env.E2E_DOCTOR_PASSWORD ?? "Doctor@12345");
  await page.screenshot({ path: `${OUT}/11-doctor-home.png`, fullPage: true });
  await page.goto("/doctor/visits");
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/12-visits.png`, fullPage: true });
  await page.goto("/doctor/templates");
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/13-templates.png`, fullPage: true });
  await page.goto("/doctor/visits/new");
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/14-new-visit.png`, fullPage: true });

  // زيارة قيد المراجعة من seed
  await page.goto("/doctor/visits");
  await page.waitForTimeout(1200);
  const review = page.getByRole("link", { name: "فتح المراجعة" }).or(page.getByRole("button", { name: "فتح المراجعة" }));
  if ((await review.count()) > 0) {
    await review.first().click();
    await page.waitForTimeout(2000);
    await page.screenshot({ path: `${OUT}/15-review.png`, fullPage: true });
  }

  await login(page, "admin", process.env.E2E_ADMIN_PASSWORD ?? "Admin@12345");
  await page.screenshot({ path: `${OUT}/04-admin.png`, fullPage: true });
  await page.goto("/admin/subscription");
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/07-subscription.png`, fullPage: true });
  await page.goto("/admin/settings");
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/08-settings.png`, fullPage: true });
});
