import { byId, state, toast } from "/assets/dashboard-core.js";
import { entityContextKey, entityDetail, entityNeighborhood } from "/assets/entity-client.js";
import { drawGraph, inspectNode, renderLegend, renderOverlayHelp, setupCanvasEvents } from "/assets/graph-view.js";
import { loadGraphRegion, renderGraphRegionBrowser } from "/assets/graph-regions.js";
import { layoutGraph, renderGraphAreaOptions, rootGroup } from "/assets/graph-model.js";
import { switchView } from "/assets/navigation.js";

import { legacyObligations } from "/assets/entity-inspector.js";
import { setupGraphSubjects } from "/assets/graph-subjects.js";

let searchTimer = null;

export function setupGraphEvents() {
  setupGraphSubjects();
  ["overlay-select", "size-select", "graph-layout-select"].forEach(id => {
    byId(id).addEventListener("change", () => { renderOverlayHelp(); renderLegend(); redrawLayout(true); });
  });
  ["graph-kind-select", "graph-relation-select", "graph-evidence-select"].forEach(id => byId(id).addEventListener("change", reloadGraph));
  byId("height-select").addEventListener("change", resizeHeight);
  byId("fit-graph-button").addEventListener("click", () => redrawLayout(true));
  byId("focus-graph-button").addEventListener("click", toggleFocus);
  byId("fullscreen-graph-button").addEventListener("click", toggleFullscreen);
  document.addEventListener("fullscreenchange", fullscreenChanged);
  byId("graph-search").addEventListener("input", () => {
    window.clearTimeout(searchTimer); searchTimer = window.setTimeout(reloadGraph, 180);
  });
  byId("architecture-regions-toggle").addEventListener("change", drawGraph);
  byId("graph-area-options").addEventListener("change", toggleArea);
  byId("graph-area-all").addEventListener("click", showAllAreas);
  byId("external-toggle").addEventListener("change", reloadGraph);
  document.addEventListener("click", handleEntityLink);
  setupCanvasEvents();
  setupResizeObserver();
}

export async function focusEntity(entityId, recordTrail = true) {
  if (recordTrail && state.selectedNode?.id && state.selectedNode.id !== entityId) {
    state.entityTrail.push(state.selectedNode.id);
    if (state.entityTrail.length > 20) state.entityTrail.shift();
  }
  const token = ++state.graphRequestToken, context = entityContextKey();
  state.graphLoaded = true;
  state.graphFocusId = entityId;
  state.entitySelectionToken += 1;
  state.selectedNode = state.graph.nodes.find(item => item.id === entityId) || { id: entityId };
  byId("inspector").textContent = "Reading the selected entity and its neighborhood…";
  switchView("graph", true);
  try {
    const graph = await entityNeighborhood(entityId, { relationship_type: byId("graph-relation-select").value, evidence_state: byId("graph-evidence-select").value });
    if (token !== state.graphRequestToken || context !== entityContextKey()) return;
    state.graph = graph;
    state.graphFocusId = entityId;
    state.hiddenGroups.clear();
    renderGraphRegionBrowser(); renderGraphAreaOptions(); redrawLayout(true);
    const node = graph.nodes.find(item => String(item.id) === String(entityId));
    if (node) await inspectNode(node);
  } catch (error) { if (token === state.graphRequestToken) toast(error.message, true); }
}

function handleEntityLink(event) {
  const button = event.target.closest("[data-entity-legacy], [data-entity-back], [data-entity-id], [data-entity-focus], [data-entity-guide], [data-module-graph]");
  if (!button) return;
  if (button.dataset.entityLegacy) { void pageLegacyObligations(button); return; }
  if (button.hasAttribute("data-entity-back")) {
    const previous = state.entityTrail.pop();
    if (previous) void focusEntity(previous, false);
    return;
  }
  const id = button.dataset.entityId || button.dataset.entityFocus || button.dataset.entityGuide || `module:${button.dataset.moduleGraph}`;
  if (button.dataset.entityGuide) {
    byId("scope-focus").value = id;
    switchView("agents");
    byId("scope-goal").focus();
  } else void focusEntity(id);
}

function resizeHeight(event) {
  const value = event.target.value === "viewport" ? "calc(100vh - 250px)" : `${event.target.value}px`;
  byId("view-graph").style.setProperty("--graph-height", value);
  window.setTimeout(() => redrawLayout(true), 0);
}

function redrawLayout(reset = false) { layoutGraph(reset); drawGraph(); }

function toggleFocus() {
  const focused = document.querySelector(".graph-layout").classList.toggle("focused");
  byId("focus-graph-button").textContent = focused ? "Show inspector" : "Focus";
  window.setTimeout(() => redrawLayout(true), 0);
}

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.querySelector(".graph-panel").requestFullscreen();
  } catch (error) { toast(`Fullscreen is unavailable: ${error.message}`, true); }
}

function fullscreenChanged() {
  byId("fullscreen-graph-button").textContent = document.fullscreenElement ? "Exit fullscreen" : "Fullscreen";
  window.setTimeout(() => redrawLayout(true), 0);
}

function toggleArea(event) {
  const input = event.target.closest("[data-graph-area]");
  if (!input) return;
  if (input.checked) state.hiddenGroups.delete(input.dataset.graphArea);
  else state.hiddenGroups.add(input.dataset.graphArea);
  if (state.selectedNode && state.hiddenGroups.has(rootGroup(state.selectedNode))) state.selectedNode = null;
  renderGraphAreaOptions(); redrawLayout(true);
}

function showAllAreas() { state.hiddenGroups.clear(); renderGraphAreaOptions(); redrawLayout(true); }
function reloadGraph() { void loadGraphRegion(state.graphRegion).catch(error => toast(error.message, true)); }

function setupResizeObserver() {
  let frame = null;
  const resize = () => {
    window.cancelAnimationFrame(frame);
    frame = window.requestAnimationFrame(() => redrawLayout(false));
  };
  window.addEventListener("resize", resize);
  if (window.ResizeObserver) new ResizeObserver(resize).observe(document.querySelector(".canvas-wrap"));
}

async function pageLegacyObligations(button) {
  const context = entityContextKey();
  button.disabled = true;
  try {
    const value = await entityDetail(button.dataset.entityLegacy, { legacy_offset: Number(button.dataset.legacyOffset), legacy_limit: 25 });
    if (button.isConnected && context === entityContextKey()) button.closest(".entity-legacy-obligations").outerHTML = legacyObligations(value.legacy_obligations, button.dataset.entityLegacy);
  } catch (error) { if (button.isConnected) { button.disabled = false; toast(error.message, true); } }
}
