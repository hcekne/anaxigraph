import { byId, state, toast } from "/assets/dashboard-core.js";
import { drawGraph, inspectNode, renderLegend, renderOverlayHelp, setupCanvasEvents } from "/assets/graph-view.js";
import { loadGraphRegion } from "/assets/graph-regions.js";
import {
  layoutGraph,
  renderGraphAreaOptions,
  rootGroup,
} from "/assets/graph-model.js";

export function setupGraphEvents() {
  ["overlay-select", "size-select"].forEach((id) => {
    byId(id).addEventListener("change", () => {
      renderOverlayHelp();
      renderLegend();
      drawGraph();
    });
  });
  byId("height-select").addEventListener("change", resizeHeight);
  byId("fit-graph-button").addEventListener("click", () => redrawLayout(true));
  byId("focus-graph-button").addEventListener("click", toggleFocus);
  byId("fullscreen-graph-button").addEventListener("click", toggleFullscreen);
  document.addEventListener("fullscreenchange", fullscreenChanged);
  byId("graph-search").addEventListener("input", drawGraph);
  byId("architecture-regions-toggle").addEventListener("change", drawGraph);
  byId("graph-area-options").addEventListener("change", toggleArea);
  byId("graph-area-all").addEventListener("click", showAllAreas);
  byId("external-toggle").addEventListener("change", reloadGraph);
  byId("inspector").addEventListener("click", inspectLinkedNode);
  setupCanvasEvents();
  setupResizeObserver();
}

function resizeHeight(event) {
  const value = event.target.value === "viewport"
    ? "calc(100vh - 250px)" : `${event.target.value}px`;
  byId("view-graph").style.setProperty("--graph-height", value);
  window.setTimeout(() => redrawLayout(true), 0);
}

function redrawLayout(reset = false) {
  layoutGraph(reset);
  drawGraph();
}

function toggleFocus() {
  const focused = document.querySelector(".graph-layout").classList.toggle("focused");
  byId("focus-graph-button").textContent = focused ? "Show inspector" : "Focus";
  window.setTimeout(() => redrawLayout(true), 0);
}

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.querySelector(".graph-panel").requestFullscreen();
  } catch (error) {
    toast(`Fullscreen is unavailable: ${error.message}`, true);
  }
}

function fullscreenChanged() {
  byId("fullscreen-graph-button").textContent = document.fullscreenElement
    ? "Exit fullscreen" : "Fullscreen";
  window.setTimeout(() => redrawLayout(true), 0);
}

function toggleArea(event) {
  const input = event.target.closest("[data-graph-area]");
  if (!input) return;
  if (input.checked) state.hiddenGroups.delete(input.dataset.graphArea);
  else state.hiddenGroups.add(input.dataset.graphArea);
  if (state.selectedNode && state.hiddenGroups.has(rootGroup(state.selectedNode))) {
    state.selectedNode = null;
    byId("inspector").innerHTML = '<p class="eyebrow">Module inspector</p><h2>Select a node</h2><p class="muted">Click a graph node to inspect it.</p>';
  }
  renderGraphAreaOptions();
  redrawLayout(true);
}

function showAllAreas() {
  state.hiddenGroups.clear();
  renderGraphAreaOptions();
  redrawLayout(true);
}

async function reloadGraph() {
  await loadGraphRegion(state.graphRegion);
}

function inspectLinkedNode(event) {
  const target = event.target.closest("[data-path]");
  if (!target?.dataset.path) return;
  const node = state.graph.nodes.find((item) => item.path === target.dataset.path);
  if (node) inspectNode(node);
}

function setupResizeObserver() {
  let frame = null;
  const resize = () => {
    window.cancelAnimationFrame(frame);
    frame = window.requestAnimationFrame(() => redrawLayout(false));
  };
  window.addEventListener("resize", resize);
  if (window.ResizeObserver) {
    new ResizeObserver(resize).observe(document.querySelector(".canvas-wrap"));
  }
}
