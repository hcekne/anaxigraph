import { expect, test } from "@playwright/test";

// Measures browser work for a declared 5,000-module synthetic query result.
// Backend scan/query performance is measured separately; timings are evidence, not a CI speed gate.
test("large-repository browsing keeps page work and transfers bounded", async ({ page }, testInfo) => {
  const transfers = [], timings = {}, errors = [], memorySamples = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/graph/entities?*", route => {
    const params = new URL(route.request().url()).searchParams;
    const limit = Number(params.get("limit")), kind = params.get("kind"), offset = Number(params.get("offset") || 0);
    const total = params.get("q") ? 17 : 5000;
    const count = Math.min(limit, total - offset);
    const nodes = Array.from({ length: Math.max(0, count) }, (_, index) => ({
      id: `${kind}:pkg/module_${offset + index}.py`, kind,
      label: `Module ${offset + index}`, path: `pkg/module_${offset + index}.py`,
      overview: "Owns a compact responsibility behind a stable interface.",
      placement: { area: "application", subsystem: "orders" },
      metrics: { lines_of_code: 5000 - offset - index, function_count: 8, fan_in: 4, fan_out: 3 }, readiness: "current",
    }));
    const edges = nodes.slice(1).map((node, index) => ({ id: `edge-${index}`, source: nodes[index].id, target: node.id, relationship_type: "calls", confidence: 1, resolution: "resolved_internal" }));
    const body = JSON.stringify({ context: { repository_id: 1, snapshot_id: 1, revision: "synthetic-5000" }, nodes, edges,
      total_nodes: total, returned_nodes: nodes.length, total_edges: Math.max(0, total - 1), returned_edges: edges.length, next_offset: offset + count < total ? offset + count : null,
      facets: { areas: ["application"], subsystems: ["orders"], languages: ["python"] },
    });
    transfers.push({ kind, limit, offset, query: params.get("q"), bytes: Buffer.byteLength(body), returned: nodes.length, total });
    return route.fulfill({ contentType: "application/json", body });
  });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  let started = performance.now();
  await page.goto("/#modules");
  await expect(page.locator(".module-row")).toHaveCount(100);
  timings.cold_module_view_ms = performance.now() - started;
  expect(transfers).toHaveLength(1);
  memorySamples.push(await memorySample(cdp, "cold modules"));
  started = performance.now();
  await page.locator('[data-module-sort="lines_of_code"]').click();
  await expect.poll(() => transfers.length).toBe(2);
  await expect(page.locator("#view-modules")).toHaveAttribute("aria-busy", "false");
  timings.global_sort_ms = performance.now() - started;
  memorySamples.push(await memorySample(cdp, "sorted modules"));
  started = performance.now();
  await page.locator("#module-search").fill("specific behavior");
  await expect(page.locator(".module-row")).toHaveCount(17);
  timings.global_search_with_debounce_ms = performance.now() - started;
  memorySamples.push(await memorySample(cdp, "searched modules"));
  started = performance.now();
  await page.getByRole("button", { name: "Graph", exact: true }).click();
  await expect(page.locator("#graph-canvas")).toHaveAttribute("data-render-state", "ready");
  await expect(page.locator("#graph-entity-list > button")).toHaveCount(50);
  timings.graph_navigation_ms = performance.now() - started;
  memorySamples.push(await memorySample(cdp, "bounded graph"));
  started = performance.now();
  await page.getByRole("button", { name: "Files", exact: true }).click();
  await expect(page.locator(".module-row")).toHaveCount(17);
  timings.warm_module_navigation_ms = performance.now() - started;
  memorySamples.push(await memorySample(cdp, "warm modules"));
  const memory = { peak_sampled_js_heap_bytes: Math.max(...memorySamples.map(item => item.JSHeapUsedSize)), samples: memorySamples };
  const result = { fixture: "synthetic 5,000-module repository query, local HTTP; backend data mocked", timings, memory, transfers,
    dom_nodes: await page.locator("*").count(), page_errors: errors };
  expect(Math.max(...transfers.map(item => item.returned))).toBeLessThanOrEqual(100);
  expect(errors).toEqual([]);
  await testInfo.attach("semantic-browser-scale.json", { body: JSON.stringify(result, null, 2), contentType: "application/json" });
  console.log(JSON.stringify(result));
});

async function memorySample(cdp, stage) {
  const { metrics } = await cdp.send("Performance.getMetrics");
  return { stage, ...Object.fromEntries(metrics.filter(item => ["JSHeapUsedSize", "JSHeapTotalSize", "Nodes", "LayoutCount"].includes(item.name)).map(item => [item.name, item.value])) };
}
