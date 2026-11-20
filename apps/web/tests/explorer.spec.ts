import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

const itw = "/?company=0000049826&duration=quarter&period=2026-2";
const fcf = "Free cash flow";
const rokw = "/?company=0001024478&duration=annual&period=2026-0&mode=platform_snapshot&dataset_version=v0002";

function metricRow(page: import("@playwright/test").Page, name: string) {
  return page.getByTestId("metric-row").filter({ has: page.getByRole("button", { name, exact: true }) });
}

test("shows the audited quarter and downloads the same chart and table data", async ({ page }) => {
  await page.goto(itw);
  await expect(metricRow(page, fcf).getByText("$631,000,000", { exact: true })).toBeVisible();
  await expect(page.getByTestId("fcf-chart").locator("canvas")).toBeVisible();
  await page.getByText("View chart data", { exact: true }).click();
  const last = page.getByTestId("chart-data-row").last();
  await expect(last).toContainText("FY2026 Q2");
  await expect(last.locator("[data-value]")).toHaveAttribute("data-value", "631000000");

  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export CSV" }).click();
  const download = await downloadEvent;
  const lines = (await readFile(await download.path(), "utf-8")).trim().split(/\r?\n/).map((line) => line.split(","));
  const table = lines.find((row) => row[0] === "selected_period" && row[4] === "free_cash_flow");
  const chart = lines.findLast((row) => row[0] === "free_cash_flow_history");
  expect(table?.slice(4, 10)).toEqual(["free_cash_flow", "USD", "631000000", "available", "2026-04-01", "2026-06-30"]);
  expect(chart?.slice(4, 10)).toEqual(table?.slice(4, 10));
  expect(chart?.[13]).toBe("v0003");
  expect(chart?.[15]).toBe("latest");
  await expect(page.locator("#filing-evidence").getByRole("link").first()).toHaveAttribute("href", /https:\/\/www\.sec\.gov\/Archives\/edgar\/data\//);
});

test("filed-by cutoff withholds the result until the filing date and keeps the URL shareable", async ({ page }) => {
  await page.goto(itw + "&mode=filed_by&filed_by=2026-08-05");
  await expect(metricRow(page, fcf)).toContainText("Missing compatible inputs");
  await page.getByLabel("Filed by date", { exact: true }).fill("2026-08-06");
  await expect(metricRow(page, fcf)).toContainText("$631,000,000");
  await expect(page).toHaveURL(/filed_by=2026-08-06/);
  await page.reload();
  await expect(page.getByLabel("Filed by date", { exact: true })).toHaveValue("2026-08-06");
  await expect(metricRow(page, fcf)).toContainText("$631,000,000");
});

test("restores old methodology and loads the annual result only in the matching snapshot", async ({ page }) => {
  await page.goto(rokw);
  await expect(metricRow(page, fcf)).toContainText("Unavailable in this snapshot");
  await page.getByLabel("Snapshot version").selectOption("v0003");
  await expect(metricRow(page, fcf)).toContainText("$1,701,000,000");
  await expect(page).toHaveURL(/dataset_version=v0003/);
  await page.getByRole("button", { name: "Trailing 12 months" }).click();
  await expect(metricRow(page, fcf)).toContainText("$1,701,000,000");
  await expect(page).toHaveURL(/duration=ttm/);
});

test("fits a phone viewport and exposes the chart data and keyboard navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(itw);
  await expect(metricRow(page, fcf)).toContainText("$631,000,000");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.getByLabel("Company", { exact: true }).selectOption("0000029905");
  await expect(page.getByRole("heading", { name: /Dover/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
