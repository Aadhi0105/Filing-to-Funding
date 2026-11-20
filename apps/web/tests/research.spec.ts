import { expect, test } from "@playwright/test";

test("navigates the six-company views and retains a pinned cutoff", async ({ page }) => {
  await page.goto("/overview?mode=filed_by&filed_by=2026-11-19");
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(6);
  await page.getByRole("link", { name: "Peer Comparison" }).click();
  await expect(page).toHaveURL(/filed_by=2026-11-19/);
  await expect(page.getByRole("row", { name: /DOV/ })).toContainText("Different reporting basis");
  await expect(page.getByRole("row", { name: /AOS/ })).toContainText("$162.9M");
  const exportEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  expect((await exportEvent).suggestedFilename()).toMatch(/^peer-comparison-v\d+\.csv$/);
  await page.getByRole("link", { name: "Data Quality & Filing History" }).click();
  await expect(page.getByRole("heading", { name: "AOS filing history" })).toBeVisible();
  await expect(page.getByText(/27 eligible filings · 4 with qualified facts/)).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Page 2")).toBeVisible();
});

test("calculates funding sensitivity on a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/funding?curve_date=2026-11-15");
  await expect(page.getByText(/Carried forward from last observation/)).toBeVisible();
  await page.getByRole("button", { name: "Calculate scenario" }).click();
  await expect(page.getByRole("heading", { name: "Incremental interest" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Funding shock sensitivity" })).toContainText("$250,000");
  await expect(page.getByRole("link", { name: "Overview" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
