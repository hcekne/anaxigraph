import {
  api,
  byId,
  escapeHtml,
  request,
  selectedRepository,
  setupTheme,
  state,
  toast,
} from "/assets/dashboard-core.js";
import { mapLayerDescription, mapLayerLabel } from "/assets/dashboard-format.js";
import {
  renderFindings,
  renderWorkflowGuide,
} from "/assets/finding-controller.js";
import { setupGraphEvents } from "/assets/graph-events.js";
import {
  initialGraphRegion,
  renderGraphRegionBrowser,
  setupGraphRegionEvents,
} from "/assets/graph-regions.js";
import { drawGraph, renderLegend, renderOverlayHelp } from "/assets/graph-view.js";
import {
  buildGroupIndex,
  layoutGraph,
  renderGraphAreaOptions,
} from "/assets/graph-model.js";
import { renderHistory, stopHistoryPlayback } from "/assets/history-controller.js";
import { setupModuleEvents } from "/assets/module-events.js";
import { renderModuleFilters, renderModules } from "/assets/module-view.js";
import { renderOverview, scheduleSemanticPoll, selectedHierarchy } from "/assets/overview-view.js";
import {
  displaySnapshot,
  renderOnboarding,
  renderRepositorySelector,
  renderSettings,
} from "/assets/repository-view.js";
import { setupWorkflowEvents } from "/assets/workflow-events.js";

async function load() {
  try {
    const [repositories, glossary] = await Promise.all([
      request("/api/repositories"), request("/api/glossary"),
    ]);
    state.repositories = repositories;
    state.glossary = glossary;
    if (!repositories.length) throw new Error("No repository has been indexed yet.");
    const requested = Number(new URLSearchParams(window.location.search).get("repository"));
    const remembered = Number(window.localStorage.getItem("anaxigraph.repository"));
    const candidate = repositories.find((item) => Number(item.id) === requested)
      || repositories.find((item) => Number(item.id) === remembered)
      || repositories.find((item) => item.default)
      || repositories[0];
    state.repositoryId = Number(candidate.id);
    renderRepositorySelector();
    renderWorkflowGuide();
    await loadRepository();
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadRepository() {
  stopHistoryPlayback();
  window.clearTimeout(state.historyPollTimer);
  window.clearTimeout(state.semanticPollTimer);
  try {
    const [overview, graphOverview] = await Promise.all([
      request(api("/api/overview")),
      request(api("/api/graph/overview")),
    ]);
    const graphRegion = initialGraphRegion(overview, graphOverview);
    const [modules, graph, findings, snapshots, trends, historyInfo, semanticStatus] = await Promise.all([
      request(api("/api/modules")),
      request(api("/api/graph", {
        node_limit: 250, edge_limit: 500, area: graphRegion,
      })),
      request(api("/api/findings", findingParams())),
      request(api("/api/snapshots")),
      request(api("/api/trends")),
      request(api("/api/history")),
      request(api("/api/semantic")),
    ]);
    Object.assign(state, {
      overview,
      graphOverview,
      graphRegion,
      modules,
      graph,
      findingPage: findings,
      findings: findings.items || [],
      snapshots,
      trends: trends.snapshots || [],
      historyInfo,
      semanticStatus,
    });
    resetRepositoryState();
    configureMapLayers();
    buildGroupIndex(selectedHierarchy());
  renderGraphAreaOptions();
  renderGraphRegionBrowser();
    const repository = selectedRepository();
    byId("project-name").textContent = repository?.name || "No repository";
    document.title = `${repository?.name || "Repository"} · AnaxiGraph`;
    displaySnapshot(overview.snapshot);
    const refresh = byId("refresh-button");
    refresh.disabled = !repository?.scannable;
    refresh.title = repository?.scannable
      ? "Refresh the configured read-only scan target"
      : "This repository is indexed but is not mounted as this server's scan target";
    renderAllViews();
  } catch (error) {
    toast(error.message, true);
  }
}

function findingParams() {
  const element = (id) => byId(id)?.value || "";
  return {
    view: element("finding-view-filter") || "attention",
    status: element("finding-status-filter"),
    severity: element("finding-severity-filter"),
    finding_type: element("finding-type-filter"),
    architecture_area: element("finding-area-filter"),
    minimum_confidence: element("finding-confidence-filter") || "0",
    module: byId("finding-module-filter")?.value.trim() || "",
  };
}

function resetRepositoryState() {
  state.moduleDetails.clear();
  state.selectedNode = null;
  state.highlightedPaths.clear();
  state.protectedPaths.clear();
  state.conflictPaths.clear();
  state.modulePage = 1;
  state.expandedModuleId = null;
  state.hiddenGroups.clear();
}

function configureMapLayers() {
  const map = state.overview?.map || {};
  const available = map.available_layers || ["effective"];
  let remembered = "";
  try {
    remembered = window.localStorage.getItem("anaxigraph.map-layer") || "";
  } catch (_) {
    // Use the autonomous map default when storage is unavailable.
  }
  state.mapLayer = available.includes(remembered) ? remembered
    : available.includes(map.default_layer) ? map.default_layer : available[0];
  const select = byId("map-layer-select");
  select.innerHTML = available.map((layer) => (
    `<option value="${escapeHtml(layer)}">${escapeHtml(mapLayerLabel(layer))}</option>`
  )).join("");
  select.value = state.mapLayer;
  select.disabled = available.length < 2;
  byId("map-layer-description").textContent = mapLayerDescription(state.mapLayer, map.source);
}

function renderAllViews() {
  renderOverview();
  scheduleSemanticPoll();
  renderOnboarding();
  renderModuleFilters();
  renderModules();
  renderSettings();
  renderFindings();
  renderHistory();
  renderOverlayHelp();
  renderLegend();
  layoutGraph();
  drawGraph();
}

state.reloadRepository = loadRepository;
setupTheme();
setupModuleEvents();
setupGraphEvents();
setupGraphRegionEvents();
setupWorkflowEvents();
load();
