import { expect, test } from "@playwright/test";

async function openDashboard(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator(".group-family").first()).toBeVisible();
}

test("dashboard exposes five actor-neutral journeys", async ({ page }) => {
  await openDashboard(page);
  const tabs = page.locator(".tabs .tab");

  await expect(tabs).toHaveCount(5);
  await expect(tabs).toHaveText(["Understand", "Guide", "Improve", "Changes", "Settings"]);
  await expect(page.locator("#journey-subnav")).toContainText("Charter & overview");
  await expect(page.locator("#journey-subnav")).toContainText("Files");
  await expect(page.locator("#journey-subnav")).toContainText("Graph");

  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await expect(page.locator("#journey-subnav")).toContainText("Findings");
  await expect(page.locator("#journey-subnav")).toContainText("Patterns");
  await expect(page.locator("#journey-subnav")).toContainText("Fresh eyes");
});

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

test("architecture cards have one code-line bar, segmented in place", async ({ page }) => {
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

  await expect(picker).toHaveValue("current");
  await picker.selectOption("declared");
  await expect(page.locator("#map-layer-description")).toContainText(
    "optional architecture intent",
  );
  await picker.selectOption("path");
  await expect(page.locator("#map-layer-description")).toContainText(
    "deterministic directory and package rules",
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
  await expect(page.locator("#history-help")).toContainText("Completed code maps remain usable");
  await expect(page.locator("#history-import-button")).toHaveText("Retry / resume history");
  await expect(page.locator("#history-cancel-button")).toBeHidden();
});

test("stale history explains the final jump instead of claiming continuity", async ({ page }) => {
  await page.route("**/api/history?**", async (route) => route.fulfill({
    json: {
      total_commits: 155,
      analyzed_commits: 7,
      timeline_frames: 8,
      timeline: {
        state: "stale",
        needs_update: true,
        saved_commit_maps: 7,
        unmapped_tail_commits: 147,
      },
      job: { status: "not_started" },
    },
  }));
  await openDashboard(page);
  await page.locator('.tab[data-view="history"]').click();

  await expect(page.locator("#history-help")).toContainText(
    "stops 147 commits before the current Git head",
  );
  await expect(page.locator("#history-help")).toContainText("not a continuous animation");
  await expect(page.locator("#history-import-button")).toHaveText("Update Git timeline");
});

test("relationship completeness and analyzer limits are visible", async ({ page }) => {
  await openDashboard(page);
  await expect(
    page.locator(".metric", { hasText: "Code links matched to files" }).locator("strong"),
  ).toContainText("%");
  const notice = page.locator("#graph-quality-notice");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("The map may miss connections because");
  await expect(notice).toContainText("What this limits");
  await expect(notice).toContainText("could read words but not code structure");
  await expect(notice).toContainText("What to do");
  await expect(notice).not.toContainText("confidence-gated");
  await page.getByRole("button", { name: "Improve", exact: true }).click();
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
  await page.getByRole("button", { name: "Improve", exact: true }).click();
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

test("graph redraw survives rapid tab changes without a white canvas", async ({ page }) => {
  await openDashboard(page);
  for (let index = 0; index < 8; index += 1) {
    await page.locator('[data-subview="graph"]').click();
    await page.locator('[data-view="overview"]').click();
  }
  await page.locator('[data-subview="graph"]').click();
  const canvas = page.locator("#graph-canvas");
  await expect(canvas).toHaveAttribute("data-render-state", "ready");
  expect(await canvas.evaluate((element) => {
    const context = element.getContext("2d");
    const pixels = context.getImageData(0, 0, element.width, element.height).data;
    for (let index = 0; index < pixels.length; index += 64) {
      if (pixels[index] || pixels[index + 1] || pixels[index + 2]) return true;
    }
    return false;
  })).toBe(true);
});

test("a slow previous repository can never overwrite a newer selection", async ({ page }) => {
  const slowRepository = {
    id: 10, name: "Slow old repository", path: "/slow", default: true, scannable: true,
  };
  const targetRepository = {
    id: 20, name: "Race target", path: "/target", default: false, scannable: true,
  };
  const snapshot = {
    id: 200, branch: "main", commit_sha: "target1234", dirty: false,
    analysis_timestamp: "2026-08-31T00:00:00Z",
  };
  const overview = (files) => ({
    files, lines_of_code: files * 10, symbols: 0, relationships: 0,
    findings: {}, languages: [], group_hierarchies: { current: [] },
    map: { available_layers: ["current"], default_layer: "current" },
    snapshot, graph_quality: {}, coverage: {}, semantic: { enabled: false },
  });
  let releaseSlowRepository;
  const slowRepositoryGate = new Promise((resolve) => { releaseSlowRepository = resolve; });
  await page.addInitScript(() => window.localStorage.removeItem("anaxigraph.repository"));
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const repositoryId = Number(url.searchParams.get("repository_id"));
    if (url.pathname === "/api/overview" && repositoryId === slowRepository.id) {
      await slowRepositoryGate;
    }
    const responses = {
      "/api/repositories": [slowRepository, targetRepository],
      "/api/glossary": { overlays: {} },
      "/api/overview": overview(repositoryId === targetRepository.id ? 222 : 111),
      "/api/modules": [],
      "/api/graph": { nodes: [], edges: [], snapshot, counts: {} },
      "/api/findings": { items: [], shown: 0, omitted: {} },
      "/api/snapshots": [],
      "/api/trends": { snapshots: [] },
      "/api/history": { total_commits: 0, analyzed_commits: 0, timeline_frames: 0, job: {} },
      "/api/semantic": { enabled: false, worker: {}, jobs: {} },
    };
    await route.fulfill({ json: responses[url.pathname] });
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("#repository-select").selectOption(String(targetRepository.id));
  await expect(page.locator("#project-name")).toHaveText(targetRepository.name);
  const fileMetric = page.locator(".metric", { hasText: "Files" }).locator("strong").first();
  await expect(fileMetric).toHaveText("222");

  releaseSlowRepository();
  await page.waitForTimeout(500);
  await expect(page.locator("#repository-select")).toHaveValue(String(targetRepository.id));
  await expect(page.locator("#project-name")).toHaveText(targetRepository.name);
  await expect(fileMetric).toHaveText("222");
});

test("architecture overview opens one graph region at a time", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Graph", exact: true }).click();
  const browser = page.locator("#graph-region-browser");
  await expect(browser).toBeVisible();
  await expect(browser).toContainText("Browse the whole repository or focus one area");
  await expect(browser.locator('[data-graph-region=""]')).toHaveClass(/active/);
  const summary = await browser.locator(".graph-region-summary p").textContent();
  const counts = summary.match(/Showing ([\d,]+) of ([\d,]+) files/);
  expect(counts).not.toBeNull();
  expect(counts[1]).toBe(counts[2]);
  const canvas = page.locator("#graph-canvas");
  await expect(canvas).toHaveAttribute("data-render-state", "ready");
  await expect.poll(() => canvas.getAttribute("data-region-count")).not.toBe("0");
  const subregions = await page.evaluate(async () => (
    await import("/assets/dashboard-core.js")
  ).state.subgroupRegions.map((region) => region.group));
  expect(subregions.length).toBeGreaterThan(2);
  expect(subregions).toContain("frontend-features");
  const testing = browser.locator('[data-graph-region="testing"]');
  await expect(testing).toContainText("files");
  await testing.click();
  await expect(browser.locator(".graph-region-summary strong")).toHaveText("Testing");
  await expect(testing).toHaveClass(/active/);
  await expect(page.locator("#graph-canvas")).toHaveAttribute("data-region-count", "1");
  await browser.locator('[data-graph-region=""]').click();
  await expect(browser.locator(".graph-region-summary strong")).toHaveText("All Files");

  const pathRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === "/api/graph" && url.searchParams.get("map_layer") === "path";
  });
  await page.locator("#map-layer-select").selectOption("path");
  await pathRequest;
  await expect(browser.locator('[data-graph-region="application"]')).toBeVisible();
  const graphLayer = await page.evaluate(async () => (
    await import("/assets/dashboard-core.js")
  ).state.graph.architecture_frame.map_layer);
  expect(graphLayer).toBe("path");
});

test("historical files replay inside today's stable architecture frame", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Graph", exact: true }).click();
  const canvas = page.locator("#graph-canvas");
  await expect(canvas).toHaveAttribute("data-render-state", "ready");
  await expect.poll(() => canvas.getAttribute("data-region-count")).not.toBe("0");
  const currentLayout = await page.evaluate(async () => (
    await import("/assets/dashboard-core.js")
  ).state.groupRegions.map((region) => [
    region.root, ...[region.x, region.y, region.width, region.height].map(Math.round),
  ]));
  const currentSubregions = await page.evaluate(async () => (
    await import("/assets/dashboard-core.js")
  ).state.subgroupRegions.map((region) => [
    region.group, ...[region.x, region.y, region.width, region.height].map(Math.round),
  ]));
  const graph = await page.evaluate(async () => (await fetch("/api/graph?node_limit=1000&edge_limit=2000")).json());
  const retained = new Set(graph.nodes.filter((_node, index) => index % 2 === 0).map((node) => node.id));
  const historical = {
    ...graph,
    snapshot: { ...graph.snapshot, id: 999999, commit_sha: "historical" },
    nodes: graph.nodes.filter((node) => retained.has(node.id)),
    edges: graph.edges.filter((edge) => retained.has(edge.source) && retained.has(edge.target)),
    architecture_frame: {
      mode: "present_day", reference_snapshot_id: graph.snapshot.id,
      historical_snapshot_id: 999999, reclassified: true,
    },
  };
  await page.route("**/api/graph?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("snapshot_id") === "999999") {
      await route.fulfill({ json: historical });
    } else await route.continue();
  });

  await page.evaluate(async () => {
    const history = await import("/assets/history-controller.js");
    await history.graphAtSnapshot(999999, true);
  });

  expect(await page.evaluate(async () => (
    await import("/assets/dashboard-core.js")
  ).state.groupRegions.map((region) => [
    region.root, ...[region.x, region.y, region.width, region.height].map(Math.round),
  ]))).toEqual(currentLayout);
  expect(await page.evaluate(async () => (
    await import("/assets/dashboard-core.js")
  ).state.subgroupRegions.map((region) => [
    region.group, ...[region.x, region.y, region.width, region.height].map(Math.round),
  ]))).toEqual(currentSubregions);
  expect(await page.evaluate(async () => (
    await import("/assets/dashboard-core.js")
  ).state.graph.architecture_frame.reclassified)).toBe(true);
  await expect(canvas).toHaveAttribute("data-render-state", "ready");
});

test("reference artifacts are excluded by default and pattern review is visible", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Files", exact: true }).click();
  await expect(page.getByRole("columnheader", { name: "Pattern idea" })).toBeVisible();
  await page.locator("#module-search").fill("feedback-log.md");
  await expect(page.locator("#module-table-body")).toContainText("No files match");

  await page.locator("#module-include-reference").check();
  await expect(page.locator("#module-table-body")).toContainText("feedback-log.md", { timeout: 10_000 });
  const feedback = page.locator(".module-row", { hasText: "feedback-log.md" });
  await expect(feedback.locator(".attention-pill.reference")).toHaveText("Reference");
  await expect(feedback.locator(".pattern-cell")).toHaveText("Not evaluated");
  await feedback.click();
  await expect(page.locator(".module-detail-row")).toContainText("Reference file");
  await expect(page.locator(".module-detail-row")).not.toContainText("attention triage");
  await page.locator('[data-module-graph="docs/feedback-log.md"]').click();
  await expect(page.locator("#inspector")).toContainText("Why this version was read");
  await expect(page.locator("#inspector")).toContainText("Fingerprints identify");
  await expect(page.locator("#inspector")).not.toContainText("Frame reason");
});

test("settings explains every connected repository and MCP handoff", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  expect(await page.locator(".settings-repository").count()).toBeGreaterThanOrEqual(1);
  await expect(page.locator(".settings-repository.current")).toHaveCount(1);
  await expect(page.locator(".settings-repository.current")).toContainText("Choose automatically");
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
    "the connected coding agent reads one saved task at a time",
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
  await page.getByRole("button", { name: "Understand", exact: true }).click();
  await expect(page.locator("#onboarding-progress-value")).toHaveText("2/4");

  await guide.getByRole("button", { name: "Hide guide" }).click();
  await expect(guide).toBeHidden();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Show guided tour" }).click();
  await expect(page.locator("#view-overview")).toBeVisible();
  await expect(guide).toBeVisible();
});
