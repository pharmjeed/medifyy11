import { test } from "@playwright/test";

/** لقطات الوضع الإنجليزي LTR — E2E_SNAPSHOTS=1. */
test.skip(process.env.E2E_SNAPSHOTS !== "1", "snapshots only on demand");

const OUT = process.env.SNAP_DIR ?? "test-results/snaps";

test("english mode snapshots", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/login");
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/en-01-login.png` });

  await page.getByPlaceholder("Facility name or commercial registration").fill("1010456789");
  await page.getByPlaceholder("dr.username").fill("dr.ahmad");
  await page.getByPlaceholder("••••••••").fill(process.env.E2E_DOCTOR_PASSWORD ?? "Doctor@12345");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/doctor");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/en-11-doctor-home.png`, fullPage: true });

  await page.goto("/doctor/visits");
  await page.waitForTimeout(1500);
  const review = page.getByRole("link", { name: "Open review" });
  if ((await review.count()) > 0) {
    await review.first().click();
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/en-15-review.png` });
  }
});
