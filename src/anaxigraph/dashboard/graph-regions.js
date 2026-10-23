import { byId, escapeAttr, escapeHtml, format, humanize, state, toast } from "/assets/dashboard-core.js";
import { entityContextKey, entityPage, normalizeGraph } from "/assets/entity-client.js";
import { structuralNotice } from "/assets/entity-inspector.js";
import { drawGraph, renderLegend, renderOverlayHelp } from "/assets/graph-view.js";
import { groupLabel, layoutGraph, renderGraphAreaOptions } from "/assets/graph-model.js";

const NODE_LIMIT = 50;

export function setupGraphRegionEvents() {
  graphRegionBrowser().addEventListener("click", event => {
    const region = event.target.closest("[data-graph-region]");
    const next = event.target.closest("[data-graph-next]");
    if (region || next) void loadGraphRegion(region ? region.dataset.graphRegion : state.graphRegion,
      next ? state.graph.next_cursor : 0).catch(error => toast(error.message, true));
  });
}

export async function loadGraphRegion(region = "", cursor = 0) {
  if (!state.overview) return;
  const token = ++state.graphRequestToken;
  const context = entityContextKey();
  state.graphLoading = true;
  state.graph = { nodes: [], edges: [] };
  drawGraph();
  byId("graph-canvas").setAttribute("aria-busy", "true");
  byId("graph-canvas").dataset.renderState = "loading";
  try {
    let value = await entityPage(graphRequestParams(null, region, cursor));
    if (state.entityGraphKind === "observed" && !value.nodes?.length && byId("graph-kind-select").value === "capability" && !byId("graph-search").value.trim()) {
      value = await entityPage({ ...graphRequestParams(null, region, cursor), kind: "module" });
      if (token === state.graphRequestToken) byId("graph-kind-select").value = "module";
    }
    if (token !== state.graphRequestToken || context !== entityContextKey()) return;
    state.graph = normalizeGraph(value);
    state.graphRegion = region;
    state.graphFocusId = null;
    state.hiddenGroups.clear();
    renderGraphRegionBrowser();
    renderGraphAreaOptions();
    layoutGraph(true);
    renderLegend(); renderOverlayHelp();
  } finally {
    if (token === state.graphRequestToken) {
      state.graphLoading = false;
      byId("graph-canvas").setAttribute("aria-busy", "false");
      drawGraph();
    }
  }
}

export function graphRequestParams(snapshotId, region = state.graphRegion, cursor = 0) {
  return {
    ...(snapshotId ? { snapshot_id: snapshotId } : {}),
    kind: byId("graph-kind-select")?.value ?? "capability",
    q: byId("graph-search")?.value.trim(),
    scope: region,
    relationship_type: byId("graph-relation-select")?.value,
    evidence_state: byId("graph-evidence-select")?.value,
    include_external: byId("external-toggle")?.checked || false,
    limit: NODE_LIMIT, offset: Number(cursor || 0), edge_limit: 300,
  };
}

export function renderGraphRegionBrowser() {
  const browser = graphRegionBrowser();
  const regions = state.entityGraphKind === "observed" ? state.overview?.group_hierarchies?.[state.mapLayer] || [] : [];
  const counts = state.graph?.counts || {};
  browser.hidden = false;
  browser.innerHTML = `<div class="graph-region-summary"><div><span>Selected revision · ${escapeHtml(humanize(state.graph.context?.graph_kind || "observed"))} graph</span><strong>${escapeHtml(state.graphFocusId ? `Neighborhood · ${state.selectedNode?.label || state.selectedNode?.name || state.graphFocusId}` : state.graphRegion ? groupLabel(state.graphRegion) : "All scopes")}</strong></div>
    <p>${graphCount(counts.page_internal_nodes, counts.matching_nodes, counts.known_nodes, "entities")} · ${graphCount(counts.page_edges, counts.matching_edges, counts.known_edges, "connections")}. Expand an entity to inspect its neighborhood.</p>
    ${structuralNotice(state.graph.context)}
    ${state.graph.next_cursor != null ? '<button class="secondary-button" type="button" data-graph-next>Next graph page</button>' : ""}</div>
    <div class="graph-region-list"><button class="graph-region ${state.graphRegion ? "" : "active"}" type="button" data-graph-region=""><span>All scopes</span><em>up to ${NODE_LIMIT} entities at once</em></button>${regions.map(regionButton).join("")}</div>`;
}

function graphCount(shown, total, known, label) {
  return total == null
    ? `${format.format(shown || 0)} ${label} shown · total unknown (${format.format(known || 0)} known)`
    : `${format.format(shown || 0)} of ${format.format(total)} ${label}`;
}

function regionButton(region) {
  const name = String(region.name || "ungrouped");
  return `<button class="graph-region ${name === state.graphRegion ? "active" : ""}" type="button" data-graph-region="${escapeAttr(name)}"><span>${escapeHtml(groupLabel(name))}</span><em>${format.format(region.files || 0)} modules</em></button>`;
}

function graphRegionBrowser() {
  const existing = byId("graph-region-browser");
  if (existing) return existing;
  const browser = document.createElement("div");
  browser.id = "graph-region-browser";
  browser.className = "graph-region-browser";
  byId("overlay-help").before(browser);
  return browser;
}
