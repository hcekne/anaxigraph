import { api, byId, request, state, toast } from "/assets/dashboard-core.js";
import { inspectNode } from "/assets/graph-view.js";
import { renderModules } from "/assets/module-view.js";
import { switchView } from "/assets/navigation.js";

export function setupModuleEvents() {
  byId("module-search").addEventListener("input", resetAndRender);
  [
    "module-area-filter", "module-subsystem-filter", "module-language-filter",
    "module-include-reference", "module-page-size",
  ].forEach((id) => byId(id).addEventListener("change", resetAndRender));
  document.querySelectorAll("[data-module-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.moduleSort;
      state.moduleSort = state.moduleSort.key === key
        ? { key, direction: state.moduleSort.direction === "asc" ? "desc" : "asc" }
        : { key, direction: ["path", "architecture_area", "summary"].includes(key) ? "asc" : "desc" };
      resetAndRender();
    });
  });
  byId("module-previous").addEventListener("click", () => {
    state.modulePage -= 1;
    renderModules();
  });
  byId("module-next").addEventListener("click", () => {
    state.modulePage += 1;
    renderModules();
  });
  byId("module-table-body").addEventListener("click", handleModuleClick);
}

function resetAndRender() {
  state.modulePage = 1;
  renderModules();
}

async function handleModuleClick(event) {
  const graphButton = event.target.closest("[data-module-graph]");
  if (graphButton) {
    const node = state.graph.nodes.find((item) => item.path === graphButton.dataset.moduleGraph);
    if (node) {
      switchView("graph");
      window.setTimeout(() => inspectNode(node), 0);
    }
    return;
  }
  const row = event.target.closest(".module-row");
  if (!row) return;
  const id = Number(row.dataset.moduleId);
  state.expandedModuleId = Number(state.expandedModuleId) === id ? null : id;
  renderModules();
  if (Number(state.expandedModuleId) !== id) return;
  const item = state.modules.find((candidate) => Number(candidate.artifact_id) === id);
  if (!item || state.moduleDetails.has(item.path)) return;
  try {
    const detail = await request(api("/api/file", {
      path: item.path,
      snapshot_id: state.overview?.snapshot?.id,
    }));
    state.moduleDetails.set(item.path, detail);
    if (Number(state.expandedModuleId) === id) renderModules();
  } catch (error) {
    toast(error.message, true);
  }
}
