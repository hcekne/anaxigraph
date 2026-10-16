import { expect, test } from "@playwright/test";

test("current views and workflows load while history and reassessment are still pending", async ({ page }) => {
  let release;
  const held = new Promise(resolve => { release = resolve; });
  const waiting = new Set();
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (["/api/history", "/api/snapshots", "/api/reassessment"].includes(path)) {
      waiting.add(path);
      await held;
    }
    await route.continue();
  });
  try {
    await page.goto("/");
    await expect(page.locator("#project-name")).not.toHaveText("Loading…");
    await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
    await expect(page.locator("#metric-grid .metric")).toHaveCount(10);
    await expect.poll(() => waiting.size).toBe(3);
    await page.getByRole("button", { name: "Workflows", exact: true }).click();
    await expect(page.locator(".workflow-node")).toHaveCount(8);
    await page.getByRole("button", { name: "Changes", exact: true }).click();
    await expect(page.locator("#history-help")).toContainText("Loading saved history");
    release();
    await expect(page.locator("#history-help")).not.toContainText("Loading saved history");
    await expect(page.locator("#architecture-reassessment h2")).not.toContainText("Checking");
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("history failure stays in the history panel and leaves current views usable", async ({ page }) => {
  await page.route("**/api/history?*", route => route.fulfill({
    status: 503, json: { detail: "History is temporarily unavailable" },
  }));
  await page.goto("/");
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
  await page.getByRole("button", { name: "Changes", exact: true }).click();
  await expect(page.locator("#history-help")).toContainText("Saved history could not be loaded");
  await page.getByRole("button", { name: "Understand", exact: true }).click();
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await expect(page.locator(".workflow-node")).toHaveCount(8);
});
