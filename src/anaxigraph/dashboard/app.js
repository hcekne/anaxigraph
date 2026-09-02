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
  reloadFindings,
  renderFindings,
  renderWorkflowGuide,
} from "/assets/finding-controller.js";
import { setupGraphEvents } from "/assets/graph-events.js";
import {
  renderGraphRegionBrowser,
  setupGraphRegionEvents,
} from "/assets/graph-regions.js";
import { drawGraph, renderLegend, renderOverlayHelp } from "/assets/graph-view.js";
import { resetFreshEyesView, setupFreshEyesView } from "/assets/fresh-eyes-view.js";
import {
  buildGroupIndex,
  layoutGraph,
  renderGraphAreaOptions,
} from "/assets/graph-model.js";
import { renderHistory, stopHistoryPlayback } from "/assets/history-controller.js";
import { setupModuleEvents } from "/assets/module-events.js";
import { renderModuleFilters, renderModules } from "/assets/module-view.js";
import { renderNavigation } from "/assets/navigation.js";
import { renderOverview, scheduleSemanticPoll, selectedHierarchy } from "/assets/overview-view.js";
import { resetPatternView, setupPatternView } from "/assets/patterns-view.js";
import { renderReassessment, setupReassessmentView } from "/assets/reassessment-view.js";
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
  const token = ++state.repositoryLoadToken;
  // Invalidate work started for the previous repository. Large repositories
  // often answer last and must never repaint a newer selection.
  state.graphRequestToken += 1;
  stopHistoryPlayback();
  window.clearTimeout(state.historyPollTimer);
  window.clearTimeout(state.semanticPollTimer);
  try {
    const overview = await request(api("/api/overview"));
    if (token !== state.repositoryLoadToken) return;
    state.overview = overview;
    configureMapLayers();
    const [modules, graph, snapshots, trends, historyInfo, semanticStatus, reassessment] = await Promise.all([
      request(api("/api/modules")),
      request(api("/api/graph", {
        node_limit: 1000, edge_limit: 2000, area: "", map_layer: state.mapLayer,
      })),
      request(api("/api/snapshots")),
      request(api("/api/trends")),
      request(api("/api/history")),
      request(api("/api/semantic")),
      loadReassessment(),
    ]);
    if (token !== state.repositoryLoadToken) return;
    Object.assign(state, {
      overview,
      graphRegion: "",
      modules,
      graph,
      findingPage: null,
      findings: [],
      snapshots,
      trends: trends.snapshots || [],
      historyInfo,
      semanticStatus,
      reassessment,
    });
    resetRepositoryState();
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
    void reloadFindings();
  } catch (error) {
    if (token === state.repositoryLoadToken) toast(error.message, true);
  }
}

async function loadReassessment() {
  try {
    return await request(api("/api/reassessment"));
  } catch (error) {
    return {
      state: "unavailable",
      plain_language: {
        conclusion: "The current repository views loaded, but architecture reassessment is temporarily unavailable.",
      },
      architectural_effects: [],
      semantic_refresh: {},
      safety: { automatic_code_changes: false },
    };
  }
}

function resetRepositoryState() {
  state.moduleDetails.clear();
  state.selectedNode = null;
  state.highlightedPaths.clear();
  state.protectedPaths.clear();
  state.modulePage = 1;
  state.expandedModuleId = null;
  state.moduleSearchResults = null;
  state.moduleSearchQuery = "";
  state.moduleSearchToken += 1;
  state.hiddenGroups.clear();
  resetPatternView();
  resetFreshEyesView();
}

function configureMapLayers() {
  const map = state.overview?.map || {};
  const available = map.available_layers || ["current"];
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
  renderReassessment();
  renderOverlayHelp();
  renderLegend();
  layoutGraph();
  drawGraph();
}

state.reloadRepository = loadRepository;
setupTheme();
renderNavigation();
setupPatternView();
setupFreshEyesView();
setupReassessmentView();
setupModuleEvents();
setupGraphEvents();
setupGraphRegionEvents();
setupWorkflowEvents();
load();
