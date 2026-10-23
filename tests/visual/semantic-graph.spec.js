import { expect, test } from "@playwright/test";
import { installSemanticFixture, semanticFixture } from "./semantic-graph-fixture.js";

async function openModules(page) {
  await page.goto("/#modules");
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator(".module-row").first()).toBeVisible();
}

test("module sorting and paging stay global without downloading all matching modules", async ({ page }) => {
  const requests = [];
  await installSemanticFixture(page);
  await page.route("**/api/graph/entities?*", route => {
    const query = new URL(route.request().url()).searchParams;
    requests.push(Object.fromEntries(query));
    const fixture = semanticFixture(), offset = Number(query.get("offset") || 0);
    const nodes = [0, 1].map(index => ({ ...fixture.nodes[0], id: `module:page-${offset + index}.py`, label: `Page module ${offset + index}` }));
    return route.fulfill({ json: { ...fixture.graph, nodes, edges: [], returned_nodes: 2, total_nodes: 5000, next_offset: offset + 100 } });
  });
  await openModules(page);
  await expect(page.locator("#module-result-count")).toContainText("2 shown · 5,000 matching modules");
  expect(requests).toHaveLength(1);
  await page.locator('[data-module-sort="lines_of_code"]').click();
  await expect.poll(() => requests.at(-1)?.direction).toBe("asc");
  expect(requests.at(-1).sort).toBe("lines_of_code");
  await page.locator("#module-next").click();
  await expect.poll(() => requests.at(-1)?.offset).toBe("100");
  await expect(page.locator(".module-row")).toHaveCount(2);
});

test("saved understanding traverses module, function, interface, contract and tests without source reads", async ({ page }) => {
  const calls = [];
  page.on("request", request => { if (request.url().includes("/api/")) calls.push(new URL(request.url()).pathname); });
  await installSemanticFixture(page);
  await openModules(page);
  await page.locator('.module-row[data-module-id="module:src/orders.py"]').click();
  await expect(page.locator(".module-detail-row")).toContainText("Saved paragraph for Order module");
  await page.locator('.module-detail-row [data-entity-id="function:src/orders.py#submit"]').first().click();
  await expect(page.locator("#inspector h2")).toHaveText("submit");
  await page.locator('#inspector [data-entity-id="interface:src/orders.py#gateway"]').first().click();
  await expect(page.locator("#inspector h2")).toHaveText("Order gateway");
  await page.locator('#inspector [data-entity-id="contract:orders#retry"]').first().click();
  await expect(page.locator("#inspector h2")).toHaveText("Order retry contract");
  await page.locator('#inspector [data-entity-id="module:tests/test_orders.py"]').first().click();
  await expect(page.locator("#inspector h2")).toHaveText("Order retry tests");
  expect(calls).not.toContain("/api/file");
});

test("late detail for a previous selection cannot replace the current entity", async ({ page }) => {
  const fixture = await installSemanticFixture(page);
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await page.route("**/api/graph/entity?*", async route => {
    const id = new URL(route.request().url()).searchParams.get("entity_id");
    if (id === fixture.nodes[1].id) await held;
    await route.fulfill({ json: fixture.detail(id) });
  });
  await page.goto("/#graph");
  await expect(page.locator("#graph-entity-list button").first()).toBeVisible();
  await page.locator(`#graph-entity-list [data-entity-id="${fixture.nodes[1].id}"]`).count();
  await page.locator('#graph-kind-select').selectOption('function');
  await expect(page.locator('#graph-entity-list [data-entity-id="function:src/orders.py#submit"]')).toBeVisible();
  await page.locator('#graph-entity-list [data-entity-id="function:src/orders.py#submit"]').click();
  await expect(page.locator('#graph-entity-list [data-entity-id="contract:orders#retry"]')).toBeVisible();
  await page.locator('#graph-entity-list [data-entity-id="contract:orders#retry"]').click();
  await expect(page.locator("#inspector h2")).toHaveText("Order retry contract");
  const late = page.waitForResponse(response => response.url().includes("entity_id=function%3Asrc%2Forders.py%23submit"));
  release();
  await (await late).finished();
  await page.evaluate(() => new Promise(requestAnimationFrame));
  await expect(page.locator("#inspector h2")).toHaveText("Order retry contract");
  await expect(page.locator("#inspector")).not.toContainText("Saved paragraph for submit");
});

test("keyboard relationships expose direction and evidence and remain contained on a phone", async ({ page }) => {
  const fixture = semanticFixture();
  fixture.nodes[1].properties = { unresolved_call_count: 3, unresolved_target_count: 2 };
  fixture.graph.context.git_metrics = { scope: "observed_window", observed_head: "fixture-head", window_commit_count: 3 };
  fixture.graph.context.structural_analysis = { reindexed: true, scope: "matching_files", reindexed_files: 2 };
  fixture.nodes[1].metrics.fan_out = 2;
  fixture.nodes[1].metrics.resolved_fan_out = 0;
  await installSemanticFixture(page, fixture);
  await page.goto("/#graph");
  await page.locator("#graph-kind-select").selectOption("function");
  await page.locator('#graph-entity-list [data-entity-id="function:src/orders.py#submit"]').focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#inspector h2")).toHaveText("submit");
  await expect(page.locator("#inspector .entity-metrics")).toContainText("Known outgoing dependencies0");
  await expect(page.locator("#inspector .entity-unresolved")).toContainText("2 unresolved call targets · 3 call sites");
  await expect(page.locator("#inspector .entity-history")).toContainText("Recent observed Git window · 3 observed commits");
  await expect(page.locator("#inspector .entity-history")).toContainText("not a guaranteed lifetime total");
  await expect(page.locator("#inspector .graph-reanalysis-note")).toContainText("Matching source files reanalyzed with current extractor (2 files)");
  await expect(page.locator("#graph-region-browser .graph-reanalysis-note")).toContainText("Original source revisions and saved AI results remain preserved");
  const relationship = page.locator(".graph-edge-row").filter({ hasText: "Requires Contract" });
  await relationship.locator("summary").click();
  await expect(relationship).toContainText("fixture relationship");
  await expect(relationship).toContainText("confidence 1");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("grouping layers preserve canonical identity and global module ordering", async ({ page }) => {
  const fixture = semanticFixture(), requests = [];
  fixture.nodes[0].architecture_layers = { current: { area: "current-area", subsystem: "current-unit" }, path: { area: "path-area", subsystem: "path-unit" } };
  await installSemanticFixture(page, fixture);
  await page.route("**/api/graph/entities?*", route => {
    const params = new URL(route.request().url()).searchParams;
    requests.push(Object.fromEntries(params));
    return route.fulfill({ json: { ...fixture.graph, nodes: [fixture.nodes[0]], edges: [], total_nodes: 1, returned_nodes: 1 } });
  });
  await openModules(page);
  await expect(page.locator(".module-row")).toContainText("Current Area");
  await page.locator("#map-layer-select").selectOption("path");
  await page.locator('[data-module-sort="architecture_area"]').click();
  await expect.poll(() => requests.at(-1).map_layer).toBe("path");
  expect(requests.at(-1).sort).toBe("architecture_area");
  await expect(page.locator(".module-row")).toContainText("Path Area");
  await expect(page.locator('.module-row[data-module-id="module:src/orders.py"]')).toBeVisible();
});

test("bounded neighborhoods disclose unknown totals and provide an entity back trail", async ({ page }) => {
  const fixture = await installSemanticFixture(page);
  await page.route("**/api/graph/neighborhood?*", route => route.fulfill({ json: {
    ...fixture.graph, total_nodes: null, total_edges: null, known_nodes: 100, known_edges: 301, bounded: true, counts_are_complete: false,
  } }));
  await openModules(page);
  await page.locator('.module-row[data-module-id="module:src/orders.py"]').click();
  await page.locator('.module-detail-row [data-entity-id="function:src/orders.py#submit"]').first().click();
  await expect(page.locator("#graph-region-browser")).toContainText("total unknown (100 known)");
  await expect(page.locator("#inspector h2")).toHaveText("submit");
  await page.locator('#inspector [data-entity-id="interface:src/orders.py#gateway"]').first().click();
  await expect(page.locator("#inspector h2")).toHaveText("Order gateway");
  await page.getByRole("button", { name: "Back to previous entity" }).click();
  await expect(page.locator("#inspector h2")).toHaveText("submit");
});

test("saved legacy obligations stay distinct and page without inventing function bindings", async ({ page }) => {
  const fixture = await installSemanticFixture(page), requests = [];
  await page.route("**/api/graph/entity?*", route => {
    const query = new URL(route.request().url()).searchParams, id = query.get("entity_id");
    const detail = fixture.detail(id), offset = Number(query.get("legacy_offset") || 0);
    requests.push(Object.fromEntries(query));
    if (id === fixture.nodes[0].id) detail.legacy_obligations = {
      items: [{ id: `contract:src/orders.py#legacy-${offset}`, kind: "contract", label: `Saved requirement ${offset}`, overview: `Original caller requirement ${offset}.`, readiness: "legacy_reused" }],
      total: 26, returned: 1, offset, limit: 25, next_offset: offset ? null : 25, function_scope: "unknown",
    };
    return route.fulfill({ json: detail });
  });
  await page.goto("/#graph");
  await page.locator('#graph-entity-list [data-entity-id="module:src/orders.py"]').click();
  const saved = page.locator("#inspector .entity-legacy-obligations");
  await expect(saved).toContainText("Saved legacy obligations · function bindings unknown");
  await expect(saved).toContainText("Original caller requirement 0.");
  await expect(saved).toContainText("1 shown of 26");
  await saved.getByRole("button", { name: "Next obligations" }).click();
  await expect(saved).toContainText("Original caller requirement 25.");
  await expect(saved.getByRole("button", { name: "Next obligations" })).toHaveCount(0);
  expect(requests.at(-1).legacy_offset).toBe("25");
  expect(requests.at(-1).legacy_limit).toBe("25");
  await saved.getByRole("button", { name: "Previous obligations" }).click();
  await expect(saved).toContainText("Original caller requirement 0.");
});

test("module columns can be selected, restored and sorted globally without losing optional metrics", async ({ page }) => {
  const queries = [];
  await installSemanticFixture(page);
  await page.route("**/api/graph/entities?*", route => {
    const query = new URL(route.request().url()).searchParams;
    queries.push(Object.fromEntries(query));
    return route.fallback();
  });
  await openModules(page);
  await expect(page.locator('[data-module-sort="lines_of_code"]')).toBeVisible();
  await expect(page.locator('[data-module-sort="complexity"]')).toHaveCount(0);
  await page.locator(".module-column-picker summary").click();
  await page.locator('#module-column-options input[value="complexity"]').check();
  await page.locator('[data-module-sort="complexity"]').click();
  await expect.poll(() => queries.at(-1).sort).toBe("complexity");
  await page.reload();
  await expect(page.locator('[data-module-sort="complexity"]')).toBeVisible();
  await page.locator(".module-column-picker summary").click();
  await page.getByRole("button", { name: "All metrics", exact: true }).click();
  await expect(page.locator('[data-module-sort="line_coverage"]')).toBeVisible();
  await expect(page.locator('[data-module-sort="interface_count"]')).toBeVisible();
  await expect(page.locator('[data-module-sort="contract_count"]')).toBeVisible();
  await page.getByRole("button", { name: "Core columns", exact: true }).click();
  await expect(page.locator('[data-module-sort="complexity"]')).toHaveCount(0);
  await expect(page.locator('#module-column-options input[value="path"]')).toBeChecked();
  await expect(page.locator('#module-column-options input[value="path"]')).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("graph evidence selection qualifies global pages and focused expansion", async ({ page }) => {
  const fixture = await installSemanticFixture(page), requests = [];
  await page.route("**/api/graph/**", route => {
    requests.push(Object.fromEntries(new URL(route.request().url()).searchParams));
    return route.fallback();
  });
  await page.goto("/#graph");
  await expect(page.locator("#graph-entity-list button").first()).toBeVisible();
  await expect(page.locator('#graph-kind-select option[value=""]')).toHaveCount(1);
  await expect(page.locator('#graph-kind-select option[value="unresolved"]')).toHaveCount(1);
  await page.locator("#graph-kind-select").selectOption("unresolved");
  await page.locator("#graph-evidence-select").selectOption("unresolved");
  await expect.poll(() => requests.at(-1)?.evidence_state).toBe("unresolved");
  expect(requests.at(-1)?.kind).toBe("unresolved");
  await page.locator("#graph-kind-select").selectOption("module");
  await page.locator("#graph-evidence-select").selectOption("inferred");
  await expect.poll(() => requests.at(-1)?.evidence_state).toBe("inferred");
  await page.locator(`#graph-entity-list [data-entity-id="${fixture.nodes[0].id}"]`).click();
  await expect(page.locator("#inspector h2")).toHaveText("Order module");
  expect(requests.filter(item => item.entity_id).every(item => item.evidence_state === "inferred" || !item.direction)).toBe(true);
});
