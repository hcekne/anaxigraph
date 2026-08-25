import {
  api,
  byId,
  delay,
  escapeHtml,
  format,
  request,
  state,
  toast,
} from "/assets/dashboard-core.js";
import { drawGraph } from "/assets/graph-view.js";
import { graphRequestParams, renderGraphRegionBrowser } from "/assets/graph-regions.js";
import { buildGroupIndex, layoutGraph, renderGraphAreaOptions } from "/assets/graph-model.js";
import { activeHistoryStates, historyStartMessage, historyView } from "/assets/history-view.js";
import { switchView } from "/assets/navigation.js";
import { displaySnapshot, renderOnboarding } from "/assets/repository-view.js";
import { selectedHierarchy } from "/assets/overview-view.js";

export function renderHistory() {
  const snapshots = state.snapshots;
  const info = state.historyInfo || {};
  const model = historyView(info, snapshots);
  const range = byId("history-range");
  range.max = Math.max(0, snapshots.length - 1);
  range.value = Math.max(0, snapshots.length - 1);
  range.disabled = snapshots.length < 2;
  byId("history-commits").innerHTML = snapshots.length
    ? `<span>${escapeHtml(String(snapshots[0].commit_sha).slice(0, 8))}</span><span>${escapeHtml(String(snapshots.at(-1).commit_sha).slice(0, 8))}</span>`
    : "";
  byId("history-help").textContent = model.help;
  byId("history-job-detail").innerHTML = model.details.map(([label, value]) => (
    `<span><strong>${escapeHtml(label)}</strong>${escapeHtml(value)}</span>`
  )).join("");
  byId("history-play-button").disabled = snapshots.length < 2;
  byId("graph-history-play-button").disabled = snapshots.length < 2;
  const importButton = byId("history-import-button");
  importButton.disabled = model.importDisabled;
  importButton.textContent = model.importLabel;
  const cancelButton = byId("history-cancel-button");
  cancelButton.hidden = !model.active;
  cancelButton.disabled = model.cancelRequested;
  showHistoryIndex(Number(range.value));
  updatePlaybackButtons();
  scheduleHistoryRefresh();
}

function scheduleHistoryRefresh() {
  window.clearTimeout(state.historyPollTimer);
  if (!activeHistoryStates.has(state.historyInfo?.job?.status)) return;
  state.historyPollTimer = window.setTimeout(refreshHistoryData, 2500);
}

async function refreshHistoryData() {
  try {
    const [snapshots, trends, historyInfo] = await Promise.all([
      request(api("/api/snapshots")),
      request(api("/api/trends")),
      request(api("/api/history")),
    ]);
    state.snapshots = snapshots;
    state.trends = trends.snapshots || [];
    state.historyInfo = historyInfo;
    renderHistory();
    renderOnboarding();
  } catch (error) {
    toast(error.message, true);
  }
}

export function showHistoryIndex(index) {
  const snapshot = state.snapshots[index];
  if (!snapshot) return;
  byId("history-range").value = String(index);
  const timestamp = snapshot.commit_timestamp || snapshot.analysis_timestamp;
  byId("history-value").textContent = `${String(snapshot.commit_sha).slice(0, 10)} · ${new Date(timestamp).toLocaleString()}`;
  const trend = state.trends.find((item) => Number(item.snapshot_id) === Number(snapshot.id));
  const metrics = trend?.metrics || {};
  const values = [
    ["LOC", metrics.total_loc ?? snapshot.lines_of_code],
    ["Artifacts", metrics.artifact_count ?? snapshot.file_count],
    ["Dependencies", metrics.dependency_count ?? snapshot.relationship_count],
    ["Cycles", metrics.cycle_count],
    ["Average degree", metrics.average_degree == null ? null : Number(metrics.average_degree).toFixed(1)],
    ["Violations", metrics.architecture_violation_count],
  ];
  byId("trend-grid").innerHTML = values.map(([label, value]) => (
    `<div class="metric"><span>${escapeHtml(label)}</span><strong>${value == null ? "—" : format.format(value)}</strong></div>`
  )).join("");
}

export async function graphAtSnapshot(snapshotId, preserveCamera = true) {
  const selectedPath = state.selectedNode?.path;
  state.graph = await request(api("/api/graph", graphRequestParams(snapshotId)));
  state.selectedNode = selectedPath
    ? state.graph.nodes.find((node) => node.path === selectedPath) || null : null;
  buildGroupIndex(selectedHierarchy());
  renderGraphAreaOptions();
  renderGraphRegionBrowser();
  const currentId = Number(state.overview?.snapshot?.id);
  displaySnapshot(state.graph.snapshot, Number(snapshotId) !== currentId);
  layoutGraph(!preserveCamera);
  drawGraph();
}

export async function toggleHistoryPlayback() {
  if (state.historyPlaying) {
    stopHistoryPlayback();
    return;
  }
  if (state.snapshots.length < 2) {
    toast("Import at least two historical snapshots before replaying.", true);
    return;
  }
  state.historyPlaying = true;
  const token = ++state.historyPlayToken;
  updatePlaybackButtons();
  switchView("graph", true);
  for (let index = 0; index < state.snapshots.length && token === state.historyPlayToken; index += 1) {
    showHistoryIndex(index);
    try {
      await graphAtSnapshot(state.snapshots[index].id, true);
    } catch (error) {
      toast(error.message, true);
      break;
    }
    await delay(900);
  }
  if (token === state.historyPlayToken) {
    state.historyPlaying = false;
    updatePlaybackButtons();
  }
}

export function stopHistoryPlayback() {
  state.historyPlayToken += 1;
  state.historyPlaying = false;
  updatePlaybackButtons();
}

function updatePlaybackButtons() {
  const label = state.historyPlaying ? "Pause replay" : "Replay history";
  if (byId("graph-history-play-button")) byId("graph-history-play-button").textContent = label;
  if (byId("history-play-button")) {
    byId("history-play-button").textContent = state.historyPlaying ? "Pause" : "Play";
  }
}

export async function startHistoryImport() {
  const button = byId("history-import-button");
  button.disabled = true;
  try {
    const value = await request(api("/api/history/import"), { method: "POST" });
    toast(historyStartMessage(value.status));
    state.historyInfo = await request(api("/api/history"));
    renderHistory();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

export async function cancelHistoryImport() {
  const button = byId("history-cancel-button");
  button.disabled = true;
  try {
    await request(api("/api/history/cancel"), { method: "POST" });
    toast("History cancellation requested. The current frame will finish safely.");
    state.historyInfo = await request(api("/api/history"));
    renderHistory();
  } catch (error) {
    toast(error.message, true);
  }
}
