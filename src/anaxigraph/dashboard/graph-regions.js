import { api, byId, escapeAttr, escapeHtml, format, humanize, request, state, toast } from "/assets/dashboard-core.js";
import { drawGraph } from "/assets/graph-view.js";
import { layoutGraph, renderGraphAreaOptions } from "/assets/graph-model.js";

const NODE_LIMIT = 250;
const EDGE_LIMIT = 500;

export function initialGraphRegion(overview, graphOverview) {
  if (Number(overview?.files || 0) <= NODE_LIMIT) return "";
  return String(graphOverview?.nodes?.[0]?.name || "");
}

export function setupGraphRegionEvents() {
  graphRegionBrowser().addEventListener("click", async (event) => {
    const region = event.target.closest("[data-graph-region]");
    const next = event.target.closest("[data-graph-next]");
    if (!region && !next) return;
    try {
      await loadGraphRegion(
        region ? region.dataset.graphRegion : state.graphRegion,
        next ? state.graph.next_cursor : "",
      );
    } catch (error) {
      toast(error.message, true);
    }
  });
}

export async function loadGraphRegion(region = "", cursor = "") {
  const snapshotId = state.graph.snapshot?.id || state.overview?.snapshot?.id;
  state.graph = await request(api("/api/graph", graphRequestParams(snapshotId, region, cursor)));
  state.graphRegion = region;
  state.selectedNode = null;
  state.hiddenGroups.clear();
  renderGraphRegionBrowser();
  renderGraphAreaOptions();
  layoutGraph(true);
  drawGraph();
  byId("inspector").innerHTML = '<p class="eyebrow">File details</p><h2>Select a file</h2><p class="muted">Click a circle to inspect that file.</p>';
}

export function graphRequestParams(snapshotId, region = state.graphRegion, cursor = "") {
  return {
    snapshot_id: snapshotId,
    include_external: byId("external-toggle")?.checked || false,
    node_limit: NODE_LIMIT,
    edge_limit: EDGE_LIMIT,
    area: region,
    cursor,
  };
}

export function renderGraphRegionBrowser() {
  const browser = graphRegionBrowser();
  const regions = state.graphOverview?.nodes || [];
  const counts = state.graph?.counts || {};
  if (!regions.length) {
    browser.hidden = true;
    return;
  }
  browser.hidden = false;
  const current = state.graphRegion || "all files";
  const shownNodes = Number(counts.page_internal_nodes || 0);
  const matchingNodes = Number(counts.matching_nodes || 0);
  const shownEdges = Number(counts.page_edges || 0);
  const matchingEdges = Number(counts.matching_edges || 0);
  browser.innerHTML = `
    <div class="graph-region-summary">
      <div><span>Browse one repository area at a time</span><strong>${escapeHtml(humanize(current))}</strong></div>
      <p>Showing ${format.format(shownNodes)} of ${format.format(matchingNodes)} files and ${format.format(shownEdges)} of ${format.format(matchingEdges)} direct code links in this area</p>
      ${state.graph?.next_cursor ? '<button class="secondary-button" type="button" data-graph-next>Show the next page</button>' : ""}
    </div>
    <div class="graph-region-list">
      <button class="graph-region ${state.graphRegion ? "" : "active"}" type="button" data-graph-region=""><span>All files</span><em>one page at a time</em></button>
      ${regions.map((region) => regionButton(region)).join("")}
    </div>`;
}

function regionButton(region) {
  const name = String(region.name || "ungrouped");
  const active = name === state.graphRegion ? "active" : "";
  return `<button class="graph-region ${active}" type="button" data-graph-region="${escapeAttr(name)}"><span>${escapeHtml(humanize(name))}</span><em>${format.format(region.files || 0)} files</em></button>`;
}

function graphRegionBrowser() {
  const existing = byId("graph-region-browser");
  if (existing) return existing;
  const browser = document.createElement("div");
  browser.id = "graph-region-browser";
  browser.className = "graph-region-browser";
  browser.hidden = true;
  byId("overlay-help").before(browser);
  return browser;
}
