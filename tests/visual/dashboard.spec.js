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

test("missing optional coverage is neutral rather than a failed scan", async ({ page }) => {
  await openDashboard(page);
  await expect(page.locator("#coverage-notice")).toBeHidden();
  await expect(page.locator(".metric", { hasText: "Line coverage" }).locator("strong"))
    .toHaveText("No report");
});

test("semantic bootstrap progress and model-backed pattern advice are visible", async ({ page }) => {
  let semanticPath = "";
  await page.route("**/api/semantic*", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fulfill({ json: { status: "started" } });
      return;
    }
    await route.fulfill({
      json: {
        enabled: true,
        state: "pending",
        semantically_ready: false,
        eligible_modules: 20,
        current: 5,
        pending: 15,
        pending_scopes: 0,
        failed: 0,
        failed_scopes: 0,
        excluded: 2,
        coverage: 0.25,
        jobs: { pending: 15 },
        budget: { paused: false },
        worker: { status: "idle" },
        repository_dossier: {
          provider: "codex",
          model: "test-model",
          confidence: 0.87,
          value: {
            summary: "A repository intelligence sidecar with a durable semantic index.",
            architecture_role: "Read-only architecture observatory and agent context service.",
            placement_guidance: "Add analyzers behind the existing analyzer protocol.",
            pattern_opportunities: [{
              name: "Analyzer strategy",
              score: 93,
              confidence: 0.9,
              rationale: "Language analyzers already share one protocol.",
              migration_cost: "low",
            }],
            consolidation_assessment: {
              recommendation: "keep",
              score: 88,
              rationale: "Keep provider transport separate from orchestration.",
              candidates: [],
            },
            dead_code_candidates: [],
            risks: ["Static edges cannot prove runtime reachability."],
          },
        },
      },
    });
  });
  await page.route("**/api/modules*", async (route) => {
    const response = await route.fetch();
    const modules = await response.json();
    const module = modules.find((item) => item.evaluation?.monitored_by_default !== false);
    semanticPath = module.path;
    module.semantic = {
      ...(module.semantic || {}),
      status: "current",
      pattern_opportunities: [{
        name: "Adapter pattern",
        scope: "module",
        score: 91,
        confidence: 0.88,
        rationale: "Fits the existing provider boundary",
        evidence: ["Several provider implementations share one contract"],
        counter_evidence: [],
        migration_cost: "low",
        preconditions: [],
      }],
    };
    await route.fulfill({ response, json: modules });
  });

  await openDashboard(page);
  await expect(page.locator(".metric", { hasText: "AI understanding" }).locator("strong"))
    .toHaveText("25.0%");
  await expect(page.locator("#semantic-notice")).toBeVisible();
  await expect(page.locator("#semantic-notice")).toContainText("15 module job(s)");
  await expect(page.locator("#semantic-notice [data-semantic-refresh]")).toBeVisible();
  await expect(page.locator("#repository-intelligence")).toBeVisible();
  await expect(page.locator("#repository-intelligence")).toContainText("Analyzer strategy · 93/100");

  await page.getByRole("button", { name: "Modules", exact: true }).click();
  await page.locator("#module-search").fill(semanticPath);
  await expect(page.locator(".pattern-cell", { hasText: "Adapter pattern" })).toContainText("AI");
  await expect(page.locator(".pattern-cell", { hasText: "Adapter pattern" })).toContainText("91/100");
});

test("agent-funded semantic mode explains the own-token MCP loop", async ({ page }) => {
  await page.route("**/api/semantic*", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fulfill({ json: { status: "started" } });
      return;
    }
    await route.fulfill({
      json: {
        enabled: true,
        provider: "agent",
        execution_mode: "coding_agent",
        state: "pending",
        semantically_ready: false,
        eligible_modules: 20,
        current: 5,
        pending: 15,
        pending_scopes: 0,
        failed: 0,
        failed_scopes: 0,
        excluded: 0,
        coverage: 0.25,
        jobs: { pending: 15 },
        budget: { paused: false },
        worker: { status: "idle" },
      },
    });
  });
  await openDashboard(page);

  await expect(page.locator("#semantic-notice")).toContainText(
    "ready for a connected coding agent through AnaxiMCP",
  );
  await expect(page.locator("#semantic-notice")).toContainText(
    "uses its own model and tokens",
  );
  await expect(page.locator("#semantic-notice [data-semantic-refresh]")).toHaveText(
    "Prepare semantic work",
  );
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.locator("#settings-semantic-command")).toContainText(
    "ANAXIGRAPH_SEMANTIC_SCHEMA",
  );
  await expect(page.locator("#settings-semantic-summary")).toContainText(
    "with its own model and tokens",
  );
});

test("relationship completeness and analyzer limits are visible", async ({ page }) => {
  await openDashboard(page);
  await expect(
    page.locator(".metric", { hasText: "Internal link resolution" }).locator("strong"),
  ).toContainText("%");
  const notice = page.locator("#graph-quality-notice");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("Graph evidence is partial");
  await expect(notice).toContainText("Dead-code suggestions are suppressed");
  await page.getByRole("button", { name: "Architecture", exact: true }).click();
  await expect(page.locator(".finding-priority").first()).toContainText("/100");
  await expect(page.locator("#finding-result-note")).toContainText("highest-priority signals");
  await expect(page.locator("#findings-table .finding-card")).toHaveCount(10);
  await expect(page.locator("#finding-show-all")).toBeVisible();
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
  await feedback.click();
  await page.locator('[data-module-graph="docs/feedback-log.md"]').click();
  await expect(page.locator("#inspector")).toContainText("Frame reason");
});

test("settings explains every connected repository and MCP handoff", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  expect(await page.locator(".settings-repository").count()).toBeGreaterThanOrEqual(1);
  await expect(page.locator(".settings-repository.current")).toHaveCount(1);
  await expect(page.locator("#settings-mcp-url")).toHaveText(`${new URL(page.url()).origin}/mcp`);
  await expect(page.locator("#settings-init-command")).toContainText("anaxigraph init .");
  await expect(page.locator("#settings-codex-command")).toHaveText(
    `codex mcp add anaxigraph --url ${new URL(page.url()).origin}/mcp`,
  );
  await expect(page.locator("#view-settings")).toContainText(
    "Run the command below in a normal terminal on the machine where Codex runs",
  );
  await expect(page.locator("#settings-semantic-summary")).toContainText(
    "Disabled for this repository",
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
