import { chromium } from "@playwright/test";
import { performance } from "node:perf_hooks";

const baseUrl = process.argv[2];
if (!baseUrl) throw new Error("Usage: node benchmarks/dashboard_render.mjs <dashboard-url>");

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const navigationStarted = performance.now();
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.locator("#project-name").waitFor({ state: "visible" });
  await page.waitForFunction(() => document.querySelector("#project-name")?.textContent !== "Loading…");
  await page.locator(".group-family").first().waitFor({ state: "visible" });
  const overviewReady = performance.now();

  const graphStarted = performance.now();
  await page.getByRole("button", { name: "Graph", exact: true }).click();
  await page.waitForFunction(() => Number(document.querySelector("#graph-canvas")?.dataset.visibleNodeCount || 0) > 0);
  const graphReady = performance.now();
  const canvas = page.locator("#graph-canvas");
  console.log(JSON.stringify({
    overview_ready_ms: Math.round(overviewReady - navigationStarted),
    graph_ready_ms: Math.round(graphReady - graphStarted),
    visible_nodes: Number(await canvas.getAttribute("data-visible-node-count")),
    architecture_regions: Number(await canvas.getAttribute("data-region-count")),
  }));
} finally {
  await browser.close();
}
