import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

async function exportRows(page: Page) {
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await readFile(await (await pending).path(), "utf8");
  const [header, ...rows] = file.trimEnd().split(/\r?\n/).map((line) =>
    Array.from(line.matchAll(/"((?:[^"]|"")*)"(?:,|$)/g), (match) => match[1].replaceAll('""', '"')));
  return rows.map((row) => Object.fromEntries(header.map((field, index) => [field, row[index]])));
}

const filedBy = "mode=filed_by&filed_by=2026-11-19";

test("exports the same overview, peer, and filing rows with the selected cutoff", async ({ page }) => {
  await page.goto(`/overview?${filedBy}`);
  await expect(page.getByRole("article").filter({ hasText: "A. O. Smith" })).toContainText("$162.9M");
  const overview = await exportRows(page);
  expect(overview).toHaveLength(18);
  expect(overview.find((row) => row.ticker === "AOS" && row.metric === "free_cash_flow")).toMatchObject({
    value: "162900000", unit: "USD", status: "available", period_end: "2026-09-30",
    mode: "filed_by", filed_by: "2026-11-19",
  });

  await page.getByRole("link", { name: "Peer Comparison" }).click();
  await expect(page.getByRole("row", { name: /DOV/ })).toContainText("Different reporting basis");
  const peers = await exportRows(page);
  expect(peers.find((row) => row.ticker === "DOV")).toMatchObject({
    value: "", status: "different_reporting_basis", basis: "continuing_operations", period_start: "2026-07-01",
    methodology_version: overview[0].methodology_version, dataset_version: overview[0].dataset_version,
  });
  await page.getByLabel("Period", { exact: true }).selectOption("annual");
  await expect(page.getByRole("row", { name: /IEX/ })).toContainText("$616.8M");

  await page.getByRole("link", { name: "Data Quality & Filing History" }).click();
  await expect(page.getByRole("heading", { name: "AOS filing history" })).toBeVisible();
  const history = await exportRows(page);
  expect(history).toHaveLength(10);
  expect(history[0]).toMatchObject({
    ticker: "AOS", page: "1", period_end: "2026-09-30", filed_on: "2026-10-29",
    accession: "0000091142-26-000104", mode: "filed_by", filed_by: "2026-11-19",
    methodology_version: overview[0].methodology_version, dataset_version: overview[0].dataset_version,
  });
  await expect(page.getByRole("link", { name: history[0].accession })).toHaveAttribute("href", history[0].filing_url);
});

test("exports funding assumptions, curve date and the primary coupon calculation", async ({ page }) => {
  await page.goto(`/funding?${filedBy}&curve_date=2026-11-15`);
  await page.getByLabel("Treasury maturity").selectOption("ten_year");
  await page.getByLabel("Spread (bps, optional)").fill("125");
  await page.getByRole("button", { name: "Calculate scenario" }).click();
  await expect(page.getByText(/10-year Treasury reference/)).toBeVisible();
  const scenario = await exportRows(page);
  expect(scenario.map((row) => [row.shock_bps, row.incremental_interest_usd])).toEqual([
    ["50", "125000"], ["100", "250000"], ["150", "375000"],
  ]);
  const selected = scenario[1];
  expect(selected).toMatchObject({
    repricing_principal_usd: "25000000", reference_maturity: "ten_year", spread_bps: "125",
    curve_cutoff: "2026-11-15", curve_observed: "2026-11-13", curve_status: "carried_forward",
    curve_vintage: "historical_vintage_unverified", mode: "filed_by", filed_by: "2026-11-19",
  });
  expect(Number(selected.shocked_interest_usd) - Number(selected.baseline_interest_usd)).toBe(250000);
  await expect(page.getByText(`Illustrative coupon ${selected.baseline_coupon_percent}% → ${selected.shocked_coupon_percent}%`)).toBeVisible();
  expect(scenario[0].shocked_interest_usd).toBe("");
});

test("keeps every view usable at phone width and makes wide tables keyboard reachable", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/overview?mode=platform_snapshot&dataset_version=v0003");
  await expect(page.getByRole("article")).toHaveCount(3);

  await page.getByRole("link", { name: "Peer Comparison" }).click();
  await expect(page).toHaveURL(/dataset_version=v0003/);
  const peers = page.getByRole("region", { name: "Peer comparison table" });
  await expect(peers).toBeVisible();
  await peers.focus();
  await expect(peers).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);

  await page.getByRole("link", { name: "Data Quality & Filing History" }).click();
  const filings = page.getByRole("region", { name: "Filing history table" });
  await expect(filings).toBeVisible();
  await expect(page.getByText(/3 issuers · 79 SEC filings/)).toBeVisible();
  await filings.focus();
  await expect(filings).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});

test("shows an explicit error and recovers after the selected snapshot can be read again", async ({ page }) => {
  const overview = "**/api/v1/overview?*";
  await page.route(overview, (route) => route.fulfill({
    status: 503,
    json: { detail: "The selected local dataset is unavailable" },
  }));
  await page.goto("/overview");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("The selected local dataset is unavailable");
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Export CSV" })).toHaveCount(0);
  await page.unroute(overview);
  await page.reload();
  await expect(page.getByRole("article")).toHaveCount(6);
  await expect(page.getByRole("button", { name: "Export CSV" })).toBeVisible();
});
