import {
  api,
  applyTheme,
  byId,
  request,
  selectedRepository,
  state,
  toast,
} from "/assets/dashboard-core.js";
import { mapLayerDescription } from "/assets/dashboard-format.js";
import { bindFindingFilters } from "/assets/findings-view.js";
import {
  handleFindingAction,
  reloadFindings,
  renderAgentResult,
} from "/assets/finding-controller.js";
import { drawGraph, renderLegend } from "/assets/graph-view.js";
import {
  buildGroupIndex,
  layoutGraph,
  renderGraphAreaOptions,
} from "/assets/graph-model.js";
import { loadGraphRegion } from "/assets/graph-regions.js";
import {
  cancelHistoryImport,
  graphAtSnapshot,
  showHistoryIndex,
  startHistoryImport,
  stopHistoryPlayback,
  toggleHistoryPlayback,
} from "/assets/history-controller.js";
import { renderModuleFilters, renderModules } from "/assets/module-view.js";
import { switchView } from "/assets/navigation.js";
import { renderOverview, scheduleSemanticPoll, selectedHierarchy } from "/assets/overview-view.js";
import {
  markOnboardingView,
  renderSettings,
  updateOnboarding,
} from "/assets/repository-view.js";

let activeScanId = null;

export function setupWorkflowEvents() {
  setupNavigationEvents();
  setupFindingEvents();
  setupHistoryEvents();
  setupRefreshEvents();
  setupAgentEvents();
  setupOnboardingEvents();
}

function setupNavigationEvents() {
  byId("theme-select").addEventListener("change", (event) => {
    applyTheme(event.target.value);
    renderOverview();
    renderGraphAreaOptions();
    layoutGraph(false);
    renderLegend();
    drawGraph();
  });
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      markOnboardingView(button.dataset.view);
      switchView(button.dataset.view);
    });
  });
  document.querySelectorAll("[data-switch]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.switch));
  });
  byId("repository-select").addEventListener("change", async (event) => {
    state.repositoryId = Number(event.target.value);
    window.localStorage.setItem("anaxigraph.repository", state.repositoryId);
    const url = new URL(window.location.href);
    url.searchParams.set("repository", state.repositoryId);
    window.history.replaceState({}, "", url);
    await state.reloadRepository?.();
  });
  byId("map-layer-select").addEventListener("change", async (event) => {
    state.mapLayer = event.target.value;
    try {
      window.localStorage.setItem("anaxigraph.map-layer", state.mapLayer);
    } catch (_) {
      // Layer selection still works without persistent browser storage.
    }
    state.hiddenGroups.clear();
    byId("map-layer-description").textContent = mapLayerDescription(
      state.mapLayer, state.overview?.map?.source,
    );
    buildGroupIndex(selectedHierarchy());
    renderOverview();
    renderModuleFilters();
    renderModules();
    try {
      await loadGraphRegion("");
      renderLegend();
    } catch (error) {
      toast(error.message, true);
    }
  });
}

function setupFindingEvents() {
  bindFindingFilters(() => reloadFindings());
  byId("finding-show-all").addEventListener("click", () => reloadFindings({ append: true }));
  byId("findings-table").addEventListener("click", (event) => {
    const button = event.target.closest("[data-finding]");
    if (button) handleFindingAction(button);
  });
}

function setupHistoryEvents() {
  byId("history-range").addEventListener("input", (event) => {
    showHistoryIndex(Number(event.target.value));
  });
  byId("history-range").addEventListener("change", async (event) => {
    stopHistoryPlayback();
    await graphAtSnapshot(state.snapshots[Number(event.target.value)]?.id);
  });
  byId("history-play-button").addEventListener("click", toggleHistoryPlayback);
  byId("graph-history-play-button").addEventListener("click", toggleHistoryPlayback);
  byId("history-import-button").addEventListener("click", startHistoryImport);
  byId("history-cancel-button").addEventListener("click", cancelHistoryImport);
}

function setupRefreshEvents() {
  byId("refresh-button").addEventListener("click", async (event) => {
    if (activeScanId) {
      try {
        await request(api("/api/scan/cancel"), { method: "POST" });
        toast("Scan cancellation requested. The current safe checkpoint will finish first.");
      } catch (error) {
        toast(error.message, true);
      }
      return;
    }
    event.target.disabled = true;
    try {
      const started = await request(api("/api/scan"), { method: "POST" });
      activeScanId = started.scan_id;
      event.target.disabled = false;
      event.target.textContent = "Cancel scan";
      toast("The read-only file scan started in the background.");
      const terminal = await pollScan(event.target);
      if (terminal.status === "complete") {
        const stats = terminal.scan;
        toast(`Scan complete: ${stats.analyzed} analyzed, ${stats.reused} reused`);
        await state.reloadRepository?.();
      } else if (terminal.status === "cancelled") {
        toast("Scan cancelled; the previous complete saved scan remains available.");
      } else {
        toast(terminal.error || "Scan failed.", true);
      }
    } catch (error) {
      toast(error.message, true);
    } finally {
      activeScanId = null;
      event.target.textContent = "Refresh scan";
      event.target.title = "";
      event.target.disabled = !selectedRepository()?.scannable;
    }
  });
  byId("semantic-notice").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-semantic-refresh]");
    if (!button) return;
    button.disabled = true;
    try {
      const result = await request(api("/api/semantic/prepare"), { method: "POST" });
      toast(result.status === "prepared"
        ? "AI mapping tasks were saved for the current scan."
        : result.recommended_action || "Run a read-only file scan before preparing AI mapping tasks.");
      state.semanticStatus = await request(api("/api/semantic"));
      renderOverview();
      scheduleSemanticPoll();
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
    }
  });
}

async function pollScan(button) {
  while (true) {
    await new Promise((resolve) => window.setTimeout(resolve, 750));
    const value = await request(api("/api/scan"));
    const count = value.total ? ` ${value.completed}/${value.total}` : "";
    button.title = `Scan ${value.phase || value.status}${count}`;
    if (!value.active) return value;
  }
}

function setupAgentEvents() {
  byId("scope-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const value = await request("/api/agent-scope", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          goal: byId("scope-goal").value,
          branch: byId("scope-branch").value || null,
          repository_id: state.repositoryId,
        }),
      });
      renderAgentResult(value, "scope");
    } catch (error) {
      toast(error.message, true);
    }
  });
  byId("impact-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const value = await request("/api/impact", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          target: byId("impact-target").value,
          repository_id: state.repositoryId,
        }),
      });
      renderAgentResult(value, "impact");
    } catch (error) {
      toast(error.message, true);
    }
  });
  byId("agent-result").addEventListener("click", copyAgentPrompt);
}

async function copyAgentPrompt(event) {
  if (event.target.id !== "copy-agent-prompt") return;
  try {
    await navigator.clipboard.writeText(state.lastAgentPrompt);
    toast("Agent prompt copied.");
  } catch (_) {
    byId("agent-prompt")?.select();
    toast("Select and copy the highlighted prompt.");
  }
}

function setupOnboardingEvents() {
  byId("onboarding-guide").addEventListener("click", handleOnboardingClick);
  byId("view-settings").addEventListener("click", copySetting);
  byId("show-onboarding-button").addEventListener("click", () => {
    updateOnboarding({ dismissed: false });
    switchView("overview");
    byId("onboarding-guide").scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

async function handleOnboardingClick(event) {
  const button = event.target.closest("[data-onboarding-action], [data-onboarding-view]");
  if (!button) return;
  if (button.dataset.onboardingAction === "dismiss") {
    updateOnboarding({ dismissed: true });
    return;
  }
  if (button.dataset.onboardingAction === "copy-agent") {
    const command = `codex mcp add anaxigraph --url ${window.location.origin}/mcp`;
    try {
      await navigator.clipboard.writeText(command);
      updateOnboarding({ agent: true });
      toast("Codex MCP command copied.");
    } catch (_) {
      toast("Clipboard access is unavailable; copy the command shown in the guide.", true);
    }
    return;
  }
  if (button.dataset.onboardingView) {
    markOnboardingView(button.dataset.onboardingView);
    switchView(button.dataset.onboardingView);
  }
}

async function copySetting(event) {
  const button = event.target.closest("[data-copy-target]");
  if (!button) return;
  try {
    await navigator.clipboard.writeText(byId(button.dataset.copyTarget)?.textContent || "");
    toast("Copied to clipboard.");
  } catch (_) {
    toast("Clipboard access is unavailable; select the text to copy it.", true);
  }
  renderSettings();
}
