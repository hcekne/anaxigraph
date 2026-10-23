import { byId, state, toast } from "/assets/dashboard-core.js";
import { entityContextKey, entityDetail } from "/assets/entity-client.js";
import { loadModulePage } from "/assets/module-loading.js";
import { renderModuleColumnChoices, renderModules, selectModuleColumns } from "/assets/module-view.js";

let searchTimer = null;

export function setupModuleEvents() {
  byId("module-search").addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(refresh, 180);
  });
  ["module-area-filter", "module-subsystem-filter", "module-language-filter", "module-include-reference", "module-page-size"]
    .forEach(id => byId(id).addEventListener("change", refresh));
  renderModuleColumnChoices();
  byId("module-column-options").addEventListener("change", () => selectModuleColumns([...byId("module-column-options").querySelectorAll("input:checked")].map(input => input.value)));
  byId("view-modules").addEventListener("click", event => { const action = event.target.closest("[data-module-columns]"); if (action) selectModuleColumns(action.dataset.moduleColumns); });
  byId("view-modules").querySelector("thead").addEventListener("click", sortModules);
  byId("module-previous").addEventListener("click", () => movePage(-1));
  byId("module-next").addEventListener("click", () => movePage(1));
  byId("module-table-body").addEventListener("click", expandModule);
}

function refresh() {
  state.modulePage = 1;
  void loadModulePage();
}

function sortModules(event) {
  const key = event.target.closest("[data-module-sort]")?.dataset.moduleSort;
  if (!key) return;
  state.moduleSort = state.moduleSort.key === key
    ? { key, direction: state.moduleSort.direction === "asc" ? "desc" : "asc" }
    : { key, direction: ["path", "architecture_area", "summary"].includes(key) ? "asc" : "desc" };
  refresh();
}

function movePage(direction) {
  state.modulePage = Math.max(1, state.modulePage + direction);
  void loadModulePage();
}

async function expandModule(event) {
  if (event.target.closest("[data-entity-id], [data-entity-focus], [data-entity-guide]")) return;
  const row = event.target.closest(".module-row");
  if (!row) return;
  const id = row.dataset.moduleId;
  state.expandedModuleId = state.expandedModuleId === id ? null : id;
  if (state.expandedModuleId) state.selectedNode = state.modules.find(item => String(item.id) === id);
  renderModules();
  if (state.expandedModuleId !== id || state.moduleDetails.has(id)) return;
  const context = entityContextKey();
  try {
    const detail = await entityDetail(id);
    if (context !== entityContextKey()) return;
    state.moduleDetails.set(id, detail);
    if (state.expandedModuleId === id) renderModules();
  } catch (error) {
    if (context === entityContextKey() && state.expandedModuleId === id) toast(error.message, true);
  }
}
