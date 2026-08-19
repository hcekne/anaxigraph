import { expect, test } from "@playwright/test";

async function openDashboard(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator(".group-family").first()).toBeVisible();
}

test("architecture cards have one LOC bar, segmented in place", async ({ page }) => {
  await openDashboard(page);
  const cards = page.locator(".group-family");
  expect(await cards.count()).toBeGreaterThan(5);

  for (let index = 0; index < await cards.count(); index += 1) {
    await expect(cards.nth(index).locator(".group-scale .bar-track")).toHaveCount(1);
    await expect(cards.nth(index).locator(".group-composition")).toHaveCount(0);
  }

  const frontend = cards.filter({ has: page.locator(".group-family-header strong", { hasText: "Frontend" }) });
  await expect(frontend).toHaveCount(1);
  expect(await frontend.locator(".group-segment").count()).toBeGreaterThan(1);
});

test("missing optional coverage is neutral rather than a failed scan", async ({ page }) => {
  await openDashboard(page);
  await expect(page.locator("#coverage-notice")).toBeHidden();
  await expect(page.locator(".metric", { hasText: "Line coverage" }).locator("strong"))
    .toHaveText("No report");
});

test("graph area labels fit and deselecting an area rebuilds the viewport", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Graph", exact: true }).click();
  const canvas = page.locator("#graph-canvas");
  await expect(canvas).toHaveAttribute("data-label-overflow", "0");
  const initialRegions = Number(await canvas.getAttribute("data-region-count"));
  const initialNodes = Number(await canvas.getAttribute("data-visible-node-count"));

  await page.locator("#graph-area-picker summary").click();
  const testing = page.locator("#graph-area-options label", { hasText: "Testing" }).locator("input");
  await expect(testing).toBeChecked();
  await testing.uncheck();

  await expect(canvas).toHaveAttribute("data-region-count", String(initialRegions - 1));
  expect(Number(await canvas.getAttribute("data-visible-node-count"))).toBeLessThan(initialNodes);
  await expect(canvas).toHaveAttribute("data-label-overflow", "0");
  await expect(page.locator("#graph-area-count")).not.toContainText("all");

  await page.locator("#graph-area-all").click();
  await expect(canvas).toHaveAttribute("data-region-count", String(initialRegions));
});

test("reference artifacts are excluded by default and pattern review is visible", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Modules", exact: true }).click();
  await expect(page.getByRole("columnheader", { name: "Pattern / rewrite" })).toBeVisible();
  await page.locator("#module-search").fill("feedback-log.md");
  await expect(page.locator("#module-table-body")).toContainText("No modules match");

  await page.locator("#module-include-reference").check();
  await expect(page.locator("#module-table-body")).toContainText("feedback-log.md", { timeout: 10_000 });
  const feedback = page.locator(".module-row", { hasText: "feedback-log.md" });
  await expect(feedback.locator(".attention-pill.reference")).toHaveText("—");
  await expect(feedback.locator(".pattern-cell")).toHaveText("Not evaluated");
});

test("settings explains every connected repository and MCP handoff", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  expect(await page.locator(".settings-repository").count()).toBeGreaterThanOrEqual(1);
  await expect(page.locator(".settings-repository.current")).toHaveCount(1);
  await expect(page.locator("#settings-mcp-url")).toHaveText(`${new URL(page.url()).origin}/mcp`);
  await expect(page.locator("#settings-registry-example")).toContainText("/repositories/my-project");
});
