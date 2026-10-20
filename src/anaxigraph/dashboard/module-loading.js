import { api, request, state, toast } from "/assets/dashboard-core.js";
import { renderModuleFilters, renderModules } from "/assets/module-view.js";

export async function loadRemainingModules(token) {
  const total = Number(state.overview?.files || 0);
  const snapshot = state.overview?.snapshot?.id;
  try {
    for (let offset = state.modules.length; offset < total; offset += 2000) {
      if (token !== state.repositoryLoadToken) return;
      const offsets = [offset, offset + 1000].filter(value => value < total);
      const pages = await Promise.all(offsets.map(value => request(api("/api/modules", {
        offset: value, limit: 1000, snapshot_id: snapshot, compact: true,
      }))));
      if (token !== state.repositoryLoadToken) return;
      state.modules.push(...pages.flat());
      renderModuleFilters();
      renderModules();
      if (pages.every(page => !page.length)) break;
    }
  } catch (error) {
    if (token === state.repositoryLoadToken) toast(`Some files are still loading: ${error.message}`, true);
  }
}
