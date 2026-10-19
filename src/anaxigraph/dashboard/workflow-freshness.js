// Saved results and current coverage are different facts after a source update.
export function applySavedProgress(flow, data) {
  if (flow.id !== "mapping" || !data.coverage?.history) return;
  const history = data.coverage.history;
  const modules = history.modules || {};
  const previous = history.taxonomy;
  const map = data.semantic?.taxonomy?.current;
  for (const item of flow.steps) {
    const counts = modules[item.id];
    if (counts) {
      item.freshness = counts;
      item.affected = (modules.affected || []).filter(row => row[item.id] !== "current");
      if (counts.refresh) markRefresh(item);
      if (counts.refresh || counts.new) {
        item.updateNote = [counts.refresh ? `${counts.refresh.toLocaleString()} to refresh` : "", counts.new ? `${counts.new.toLocaleString()} first run` : ""].filter(Boolean).join(" · ");
      }
      if (modules.reuse_pending && modules.saved?.[item.id]) {
        item.saved = modules.saved[item.id];
        item.reusePending = modules.previous_snapshot_id;
        item.updateNote = "New scan · reuse check pending";
        markRefresh(item);
      }
    }
    if (previous && ["taxonomy_proposal", "taxonomy_review"].includes(item.id)) {
      item.previous = previous;
      const carriedReview = map?.source === "reused_taxonomy_proposal" && item.id === "taxonomy_review" && !item.done;
      if ((!map || carriedReview) && (item.id === "taxonomy_proposal" || previous.reviews || previous.failed_reviews)) {
        item.saved = item.id === "taxonomy_proposal" ? 1 : previous.reviews;
        item.savedTotal = item.id === "taxonomy_review" ? previous.required_reviews : 1;
        item.updateNote = item.id === "taxonomy_proposal" ? "Saved map · reuse checked after files" : `${previous.failed_reviews ? `${previous.failed_reviews} failed earlier · ` : ""}Earlier source`;
        markRefresh(item);
      }
    }
    if (item.id === "taxonomy_proposal" && map?.source === "reused_taxonomy_proposal") item.updateNote = "Saved proposal reused";
  }
  const needsUpdate = flow.steps.some(item => item.status === "refresh_needed");
  if (!needsUpdate) return;
  const next = flow.steps.find(item => !["complete", "skipped"].includes(item.status));
  flow.update = { next: next?.id, nextTitle: next?.title,
    summary: modules.reuse_pending ? "The new source scan needs a reuse check. Saved results are retained; the update first checks which ones are still current." : `${modules.intrinsic?.current || 0} descriptions and ${modules.context?.current || 0} context results are current. Saved proposals remain available for reuse.`,
    commit: history.commit_sha?.slice(0, 7) };
}

function markRefresh(item) {
  if (!["running", "failed", "interrupted", "complete", "skipped"].includes(item.status)) item.status = "refresh_needed";
}
