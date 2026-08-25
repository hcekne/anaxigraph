import { expect, test } from "@playwright/test";

async function openDashboard(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator(".group-family").first()).toBeVisible();
}

test("Constellation light is the default and theme choices persist", async ({ page }) => {
  await openDashboard(page);
  const root = page.locator("html");
  const picker = page.locator("#theme-select");

  await expect(root).toHaveAttribute("data-theme", "constellation-light");
  await expect(picker).toHaveValue("constellation-light");
  await expect(picker.locator("option")).toHaveCount(4);
  expect(await page.evaluate(() => (
    getComputedStyle(document.documentElement).getPropertyValue("--bg").trim()
  ))).toBe("#f5f2ec");
  await expect(page.locator(".onboarding-step code")).toHaveCSS("color", "rgb(17, 101, 125)");

  for (const theme of ["constellation-dark", "high-contrast", "anaxigraph"]) {
    await picker.selectOption(theme);
    await expect(root).toHaveAttribute("data-theme", theme);
  }

  await picker.selectOption("constellation-dark");
  await page.reload();
  await expect(root).toHaveAttribute("data-theme", "constellation-dark");
  await expect(picker).toHaveValue("constellation-dark");
});

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

test("map layers update their hierarchy explanation", async ({ page }) => {
  await openDashboard(page);
  const picker = page.locator("#map-layer-select");

  await picker.selectOption("policy");
  await expect(page.locator("#map-layer-description")).toContainText(
    "Repository-configured path groups only",
  );
  await picker.selectOption("inferred");
  await expect(page.locator("#map-layer-description")).toContainText(
    "Deterministic path inference only",
  );
});

test("missing optional coverage is neutral rather than a failed scan", async ({ page }) => {
  await openDashboard(page);
  await expect(page.locator("#coverage-notice")).toBeHidden();
  await expect(page.locator(".metric", { hasText: "Line coverage" }).locator("strong"))
    .toHaveText("No report");
});

test("durable history progress is actionable without blocking current views", async ({ page }) => {
  let cancelled = false;
  await page.route("**/api/history**", async (route) => {
    if (route.request().method() === "POST") {
      cancelled = route.request().url().includes("/cancel");
      await route.fulfill({ json: { cancelled, status: cancelled ? "cancelled" : "started" } });
      return;
    }
    await route.fulfill({
      json: {
        total_commits: 80,
        analyzed_commits: 5,
        timeline_frames: 5,
        job: cancelled ? {
          id: 42,
          status: "cancelled",
          error: "Cancelled after the last complete frame",
          elapsed_seconds: 13,
          last_complete_snapshot_id: 17,
        } : {
          id: 42,
          status: "importing",
          completed_frames: 5,
          total_frames: 16,
          current_commit_sha: "1234567890abcdef",
          current_commit_subject: "Split architecture service",
          current_commit_date: "2026-08-20T12:00:00+00:00",
          changed_files: 91,
          analyzed_files: 87,
          re_resolved_files: 12,
          reused_files: 1400,
          rows_added: 7300,
          bytes_added: 2097152,
          elapsed_seconds: 13,
          eta_seconds: 29,
          last_complete_snapshot_id: 17,
        },
      },
    });
  });
  await openDashboard(page);
  await page.locator('.tab[data-view="history"]').click();

  await expect(page.locator("#history-help")).toContainText("Split architecture service");
  await expect(page.locator("#history-help")).toContainText("remain available");
  await expect(page.locator("#history-job-detail")).toContainText("Estimated remaining");
  await expect(page.locator("#history-job-detail")).toContainText("2.0 MiB");
  await expect(page.locator("#history-cancel-button")).toBeVisible();
  await expect(page.locator("#history-import-button")).toBeDisabled();

  await page.locator("#history-cancel-button").click();
  await expect(page.locator("#history-help")).toContainText("Completed frames remain usable");
  await expect(page.locator("#history-import-button")).toHaveText("Retry / resume history");
  await expect(page.locator("#history-cancel-button")).toBeHidden();
});

test("relationship completeness and analyzer limits are visible", async ({ page }) => {
  await openDashboard(page);
  await expect(
    page.locator(".metric", { hasText: "Internal link resolution" }).locator("strong"),
  ).toContainText("%");
  const notice = page.locator("#graph-quality-notice");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("The map may miss connections because");
  await expect(notice).toContainText("What this limits");
  await expect(notice).toContainText("could read words but not code structure");
  await expect(notice).toContainText("What to do");
  await expect(notice).not.toContainText("confidence-gated");
  await page.getByRole("button", { name: "Architecture", exact: true }).click();
  await expect(page.locator("#finding-result-note")).toContainText("findings to check");
  expect(await page.locator("#findings-table .finding-card").count()).toBeLessThanOrEqual(20);
  await expect(page.locator("#findings-table .finding-card", { hasText: "reviews functions above 25 lines" }))
    .toHaveCount(0);

  await page.locator("#finding-view-filter").selectOption("diagnostics");
  await expect(page.locator("#finding-result-note")).toContainText(
    "This complete view keeps every finding",
  );
  await expect(page.locator("#finding-type-filter option", { hasText: "Function has many lines" }))
    .toHaveCount(1);
  await page.locator("#finding-type-filter").selectOption("long_function");
  await expect(page.locator("#finding-result-note")).toContainText("matching findings");
  await expect(page.locator("#finding-groups")).toContainText("Function has many lines");
  expect(await page.locator("#findings-table .finding-card").count()).toBeLessThanOrEqual(50);
  const firstFinding = page.locator("#findings-table .finding-card").first();
  await expect(firstFinding).toContainText("What AnaxiGraph saw");
  await expect(firstFinding).toContainText("Why this matters");
  await expect(firstFinding).toContainText("What to do");
  await expect(firstFinding).toContainText("This may be fine when");
  await expect(firstFinding).toContainText("How to check the result");
  await expect(firstFinding.locator("details")).toHaveCount(0);
  await expect(firstFinding.locator(".finding-meta")).not.toContainText("priority");
  await expect(firstFinding.locator(".finding-meta")).not.toContainText("confidence");
  if (await page.locator("#finding-show-all").isVisible()) {
    const before = await page.locator("#findings-table .finding-card").count();
    await page.locator("#finding-show-all").click();
    await expect.poll(() => page.locator("#findings-table .finding-card").count())
      .toBeGreaterThan(before);
  }
});

test("finding review and accepted-risk actions persist through the ledger", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Architecture", exact: true }).click();
  await page.locator("#finding-view-filter").selectOption("diagnostics");
  const first = page.locator("#findings-table .finding-card", { has: page.getByRole("button", { name: "Mark reviewed" }) }).first();
  const summary = (await first.locator("h3").textContent()).trim();

  await first.getByRole("button", { name: "Mark reviewed" }).click();
  const reviewed = page.locator("#findings-table .finding-card", { hasText: summary });
  await expect(reviewed.locator(".finding-meta")).toContainText("Reviewed");
  await reviewed.getByRole("button", { name: "Accept risk" }).click();
  const accepted = page.locator("#findings-table .finding-card", { hasText: summary });
  await expect(accepted.locator(".finding-meta")).toContainText("Accepted risk");
  await accepted.getByRole("button", { name: "Reopen" }).click();
  await expect(page.locator("#findings-table .finding-card", { hasText: summary }).locator(".finding-meta"))
    .toContainText("Reviewed");
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

test("architecture overview opens one bounded graph region at a time", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Graph", exact: true }).click();
  const browser = page.locator("#graph-region-browser");
  await expect(browser).toBeVisible();
  await expect(browser).toContainText("Architecture-first explorer");
  const testing = browser.locator('[data-graph-region="testing"]');
  await expect(testing).toContainText("modules");
  await testing.click();
  await expect(browser.locator(".graph-region-summary strong")).toHaveText("Testing");
  await expect(testing).toHaveClass(/active/);
  await expect(page.locator("#graph-canvas")).toHaveAttribute("data-region-count", "1");
  await browser.locator('[data-graph-region=""]').click();
  await expect(browser.locator(".graph-region-summary strong")).toHaveText("All Modules");
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
  await feedback.click();
  await page.locator('[data-module-graph="docs/feedback-log.md"]').click();
  await expect(page.locator("#inspector")).toContainText("Frame reason");
});

test("settings explains every connected repository and MCP handoff", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  expect(await page.locator(".settings-repository").count()).toBeGreaterThanOrEqual(1);
  await expect(page.locator(".settings-repository.current")).toHaveCount(1);
  await expect(page.locator(".settings-repository.current")).toContainText("Auto");
  await expect(page.locator("#settings-mcp-url")).toHaveText(`${new URL(page.url()).origin}/mcp`);
  await expect(page.locator("#settings-init-command")).toContainText("anaxigraph init .");
  await expect(page.locator("#settings-codex-command")).toHaveText(
    `codex mcp add anaxigraph --url ${new URL(page.url()).origin}/mcp`,
  );
  await expect(page.locator("#view-settings")).toContainText(
    "Run the command below in a normal terminal on the machine where Codex runs",
  );
  await expect(page.locator("#settings-semantic-summary")).toContainText(
    "AI mapping is turned off for this repository",
  );
  await expect(page.locator("#view-settings")).toContainText(
    "the connected coding agent can claim bounded evidence",
  );
});

test("first-run tour explains the workflow and can be reopened", async ({ page }) => {
  await openDashboard(page);
  const guide = page.locator("#onboarding-guide");
  await expect(guide).toBeVisible();
  await expect(page.locator("#onboarding-progress-value")).toHaveText("1/4");
  await expect(guide).toContainText("Read-only repository");
  await expect(guide).toContainText("AnaxiIndex");
  await expect(guide).toContainText("AnaxiMCP");
  await expect(guide).toContainText("normal terminal on the machine where Codex runs");
  await expect(guide).toContainText(
    `codex mcp add anaxigraph --url ${new URL(page.url()).origin}/mcp`,
  );

  await guide.getByRole("button", { name: "Open architecture graph" }).click();
  await expect(page.locator("#view-graph")).toBeVisible();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page.locator("#onboarding-progress-value")).toHaveText("2/4");

  await guide.getByRole("button", { name: "Hide guide" }).click();
  await expect(guide).toBeHidden();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Show guided tour" }).click();
  await expect(page.locator("#view-overview")).toBeVisible();
  await expect(guide).toBeVisible();
});
