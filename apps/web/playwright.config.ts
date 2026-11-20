import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: false,
  use: {
    baseURL: process.env.FILING_WEB_TEST_ORIGIN || "http://127.0.0.1:3000",
    channel: process.env.FILING_BROWSER_CHANNEL || undefined,
    trace: "retain-on-failure",
  },
});
