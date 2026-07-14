import { defineConfig } from "@playwright/test";

/** e2e واحد: الرحلة الكاملة بالـ mocks (DOC-17) — يتطلب backend على 8000 وfrontend dev على 3000. */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    locale: "ar-SA",
    trace: "retain-on-failure",
  },
  webServer: process.env.E2E_NO_SERVER === "1" ? undefined : {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
