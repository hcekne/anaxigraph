import { byId, state, toast } from "/assets/dashboard-core.js";
import { entityContextKey, entityPage, moduleQuery, normalizeEntity } from "/assets/entity-client.js";
import { renderModuleFilters, renderModules } from "/assets/module-view.js";

export async function loadModulePage() {
  if (!state.repositoryId || !state.overview) return;
  const token = ++state.moduleSearchToken;
  const context = entityContextKey();
  state.moduleLoading = true;
  state.moduleError = null;
  renderModules();
  try {
    const value = await entityPage(moduleQuery());
    if (token !== state.moduleSearchToken || context !== entityContextKey()) return;
    state.moduleEnvelope = value;
    state.modules = (value.nodes || []).map(normalizeEntity);
    state.expandedModuleId = null;
    renderModuleFilters();
  } catch (error) {
    if (token === state.moduleSearchToken) {
      state.moduleError = `Module page unavailable: ${error.message}`;
      toast(error.message, true);
    }
  } finally {
    if (token === state.moduleSearchToken) { state.moduleLoading = false; renderModules(); }
  }
}
