import { test } from "@playwright/test";

/** أداة تشخيص: تفتح كل الصفحات وتلتقط أخطاء المتصفح (pageerror/console.error) — E2E_SNAPSHOTS=1. */
test.skip(process.env.E2E_SNAPSHOTS !== "1", "diagnostics only on demand");

const ADMIN_PAGES = ["/admin", "/admin/clinics", "/admin/doctors", "/admin/subscription", "/admin/settings", "/admin/analytics", "/admin/audit", "/profile"];
const DOCTOR_PAGES = ["/doctor", "/doctor/visits", "/doctor/templates", "/doctor/visits/new", "/profile"];

async function login(page: import("@playwright/test").Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByPlaceholder("اسم المنشأة أو السجل التجاري").fill("1010456789");
  await page.getByPlaceholder("dr.username").fill(username);
  await page.getByPlaceholder("••••••••").fill(password);
  await page.getByRole("button", { name: "دخول" }).click();
  await page.waitForTimeout(2000);
}

test("crawl all pages for client exceptions", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("medify_lang", "ar"));
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`[pageerror] ${page.url()} :: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`[console] ${page.url()} :: ${message.text().slice(0, 300)}`);
  });

  await page.goto("/");
  await page.waitForTimeout(1500);

  await login(page, "admin", process.env.E2E_ADMIN_PASSWORD ?? "Admin@12345");
  for (const path of ADMIN_PAGES) {
    await page.goto(path);
    await page.waitForTimeout(1800);
  }

  await login(page, "dr.ahmad", process.env.E2E_DOCTOR_PASSWORD ?? "Doctor@12345");
  for (const path of DOCTOR_PAGES) {
    await page.goto(path);
    await page.waitForTimeout(1800);
  }
  // زيارة قيد المراجعة + تفاصيل مرفوعة
  await page.goto("/doctor/visits");
  await page.waitForTimeout(1500);
  const review = page.getByRole("link", { name: "فتح المراجعة" });
  if ((await review.count()) > 0) {
    await review.first().click();
    await page.waitForTimeout(2500);
  }
  await page.goto("/doctor/visits");
  await page.waitForTimeout(1200);
  const readOnly = page.getByRole("link", { name: "عرض للقراءة" }).or(page.getByRole("button", { name: "عرض للقراءة" }));
  if ((await readOnly.count()) > 0) {
    await readOnly.first().click();
    await page.waitForTimeout(2200);
  }

  console.log("========== ERRORS (" + errors.length + ") ==========");
  for (const line of errors) console.log(line);
});
