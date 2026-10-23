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
  renderWorkflowGuide,
} from "/assets/finding-controller.js";
import { focusEntity, setupGraphEvents } from "/assets/graph-events.js";
import {
  setupGraphRegionEvents,
} from "/assets/graph-regions.js";
import { resetFreshEyesView, setupFreshEyesView } from "/assets/fresh-eyes-view.js";
import {
  buildGroupIndex,
} from "/assets/graph-model.js";
import { refreshHistoryData, renderHistory, stopHistoryPlayback } from "/assets/history-controller.js";
import { setupModuleEvents } from "/assets/module-events.js";
import { loadModulePage } from "/assets/module-loading.js";
import { useObservedSubject } from "/assets/graph-subjects.js";
import { clearEntityState } from "/assets/entity-client.js";
import { loadGraphRegion } from "/assets/graph-regions.js";
import { renderModuleFilters, renderModules } from "/assets/module-view.js";
import { renderNavigation } from "/assets/navigation.js";
import { renderOverview, scheduleSemanticPoll, selectedHierarchy } from "/assets/overview-view.js";
import { resetPatternView, setupPatternView } from "/assets/patterns-view.js";
import { renderReassessment, setupReassessmentView } from "/assets/reassessment-view.js";
import {
  displaySnapshot,
  loadRecordDelivery,
  renderOnboarding,
  renderRepositorySelector,
  renderSettings,
} from "/assets/repository-view.js";
import { setupWorkflowEvents } from "/assets/workflow-events.js";
import { resetWorkflowsView, setupWorkflowsView, workflowRepositoryLoadFailed } from "/assets/workflows-view.js";

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
    workflowRepositoryLoadFailed(error);
    toast(error.message, true);
  }
}

const loadedViews = new Set();

async function loadRepository() {
  const token = ++state.repositoryLoadToken;
  state.graphRequestToken += 1;
  stopHistoryPlayback();
  window.clearTimeout(state.historyPollTimer);
  window.clearTimeout(state.semanticPollTimer);
  loadedViews.clear();
  clearEntityState();
  Object.assign(state, { overview: null, semanticStatus: null, modules: [], graph: { nodes: [], edges: [] }, graphLoaded: false,
    snapshots: [], trends: [], historyInfo: { loading: true }, reassessment: null, findingPage: null, findings: [] });
  resetRepositoryState();
  showSelectedRepository();
  resetWorkflowsView();
  void loadSemanticStatus(token);
  try {
    const overview = await request(api("/api/overview"));
    if (token !== state.repositoryLoadToken) return;
    state.overview = overview;
    configureMapLayers();
    displaySnapshot(overview.snapshot);
    buildGroupIndex(selectedHierarchy());
    renderOverview(); renderOnboarding(); renderSettings();
    renderModuleFilters(); renderModules();
    document.querySelector("main").setAttribute("aria-busy", "false");
    window.dispatchEvent(new CustomEvent("anaxigraph:contextready"));
    void loadActiveView();
  } catch (error) {
    if (token !== state.repositoryLoadToken) return;
    byId("snapshot-label").textContent = `Saved overview unavailable: ${error.message}`;
    document.querySelector("main").setAttribute("aria-busy", "false");
    toast(error.message, true);
  }
}

async function loadSemanticStatus(token) {
  try {
    const value = await request(api("/api/semantic"));
    if (token !== state.repositoryLoadToken) return;
    state.semanticStatus = value;
    renderSettings();
    if (state.overview) renderOverview();
    scheduleSemanticPoll();
  } catch (_) { /* Workflow and structural views report their own readiness. */ }
}

async function loadActiveView(name = window.location.hash.slice(1).split("/")[0]) {
  if (!state.overview) return;
  restoreCurrentContext(name);
  if (name === "modules") { useObservedSubject(); if (!state.moduleEnvelope) await loadModulePage(); return; }
  if (name === "graph") {
    if (state.selectedNode?.id && state.graphFocusId !== state.selectedNode.id) { await focusEntity(state.selectedNode.id); return; }
    if (!state.graphLoaded) { state.graphLoaded = true; await loadGraphRegion(""); }
    return;
  }
  if (loadedViews.has(name)) return;
  loadedViews.add(name);
  if (name === "settings") void loadRecordDelivery();
  if (["architecture", "overview"].includes(name)) void reloadFindings();
  if (name === "history") {
    const token = state.repositoryLoadToken;
    renderReassessment(); renderHistory();
    void refreshReassessment(token);
    void refreshHistoryData().then(() => { if (token === state.repositoryLoadToken) renderReassessment(); });
  }
}

function restoreCurrentContext(name) {
  if (["graph", "modules"].includes(name) || !state.entitySnapshotId) return;
  state.entitySnapshotId = null;
  state.entitySelectionToken += 1;
  state.graphRequestToken += 1;
  state.graphLoaded = false;
  state.moduleEnvelope = null;
  state.moduleDetails.clear();
  state.selectedNode = null;
  buildGroupIndex(selectedHierarchy());
  displaySnapshot(state.overview.snapshot);
}

window.addEventListener("anaxigraph:viewchange", ({ detail }) => {
  void loadActiveView(detail.name).catch(error => toast(error.message, true));
});

function showSelectedRepository() {
  const repository = selectedRepository();
  byId("project-name").textContent = repository?.name || "No repository";
  document.title = `${repository?.name || "Repository"} · AnaxiGraph`;
  document.querySelector("main").setAttribute("aria-busy", "true");
  byId("snapshot-label").textContent = "Loading the saved map…";
  const refresh = byId("refresh-button");
  refresh.disabled = !repository?.scannable;
  refresh.title = repository?.scannable
    ? "Refresh the configured read-only scan target"
    : "This repository is indexed but is not mounted as this server's scan target";
}

const comparisonBaselines = new Map();

async function refreshReassessment(token, fromSnapshot) {
  const repositoryId = state.repositoryId;
  if (fromSnapshot !== undefined) comparisonBaselines.set(repositoryId, fromSnapshot);
  const value = await loadReassessment(comparisonBaselines.get(repositoryId));
  if (token !== state.repositoryLoadToken) return;
  state.reassessment = value;
  renderReassessment();
}

async function loadReassessment(fromSnapshot = null) {
  try {
    return await request(api("/api/reassessment", fromSnapshot ? { from_snapshot_id: fromSnapshot } : {}));
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

document.addEventListener("anaxigraph-reassessment-baseline", event => {
  void refreshReassessment(state.repositoryLoadToken, event.detail);
});

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

state.reloadRepository = loadRepository;
setupTheme();
setupPatternView();
setupFreshEyesView();
setupWorkflowsView();
renderNavigation();
setupReassessmentView();
setupModuleEvents();
setupGraphEvents();
setupGraphRegionEvents();
setupWorkflowEvents();
load();
