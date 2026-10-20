// Saved results and current coverage are different facts after a source update.
export function applySavedProgress(flow, data) {
  if (flow.id !== "mapping" || !data.coverage?.history) return;
  const history = data.coverage.history;
  const modules = history.modules || {};
  const previous = history.taxonomy;
  const map = data.semantic?.taxonomy?.current;
  for (const item of flow.steps) {
    applyModuleProgress(item, modules);
    applyTaxonomyProgress(item, previous, map);
    if (item.id === "taxonomy_proposal" && map?.source === "reused_taxonomy_proposal") item.updateNote = "Saved proposal reused";
  }
  const needsUpdate = flow.steps.some(item => item.status === "refresh_needed");
  if (!needsUpdate) return;
  const next = flow.steps.find(item => !["complete", "skipped"].includes(item.status));
  flow.update = { next: next?.id, nextTitle: next?.title,
    summary: modules.reuse_pending ? "The new source scan needs a reuse check. Saved results are retained; the update first checks which ones are still current." : `${modules.intrinsic?.current || 0} descriptions and ${modules.context?.current || 0} context results are current. Saved proposals remain available for reuse.`,
    commit: history.commit_sha?.slice(0, 7) };
}

function applyModuleProgress(item, modules) {
  const counts = modules[item.id];
  if (!counts) return;
  item.freshness = counts;
  item.affected = (modules.affected || []).filter(row => row[item.id] !== "current");
  if (counts.refresh) markRefresh(item);
  item.updateNote = [counts.refresh ? `${counts.refresh.toLocaleString()} to refresh` : "", counts.new ? `${counts.new.toLocaleString()} first run` : ""].filter(Boolean).join(" · ");
  if (modules.reuse_pending && modules.saved?.[item.id]) {
    item.saved = modules.saved[item.id];
    item.reusePending = modules.previous_snapshot_id;
    item.updateNote = "New scan · reuse check pending";
    markRefresh(item);
  }
}

function applyTaxonomyProgress(item, previous, map) {
  if (!previous || !["taxonomy_proposal", "taxonomy_review"].includes(item.id)) return;
  item.previous = previous;
  const proposal = item.id === "taxonomy_proposal";
  const carriedReview = map?.source === "reused_taxonomy_proposal" && !proposal && !item.done;
  if (map && !carriedReview) return;
  if (!proposal && !previous.reviews && !previous.failed_reviews) return;
  item.saved = proposal ? 1 : previous.reviews;
  item.savedTotal = proposal ? 1 : previous.required_reviews;
  const failed = previous.failed_reviews ? `${previous.failed_reviews} failed earlier · ` : "";
  item.updateNote = proposal ? "Saved map · reuse checked after files" : `${failed}Earlier source`;
  markRefresh(item);
}

function markRefresh(item) {
  if (!["running", "failed", "interrupted", "complete", "skipped"].includes(item.status)) item.status = "refresh_needed";
}
