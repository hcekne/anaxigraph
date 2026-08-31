const format = new Intl.NumberFormat();

export const activeHistoryStates = new Set([
  "queued", "enumerating", "importing", "finalizing",
]);

export function historyStartMessage(status) {
  if (status === "started") return "Git history import started.";
  if (status === "resumed") return "Git history import resumed.";
  return "Git history import is already running.";
}

export function historyView(info, snapshots) {
  const job = info.job || {};
  const timeline = info.timeline || {};
  const active = activeHistoryStates.has(job.status);
  return {
    active,
    cancelRequested: Boolean(job.cancel_requested),
    help: historyHelp(info, snapshots, job, timeline),
    details: jobDetails(job),
    importDisabled: Number(info.total_commits || 0) < 1 || active,
    importLabel: active
      ? "Importing history…"
      : ["failed", "cancelled"].includes(job.status)
        ? "Retry / resume history"
        : timeline.needs_update ? "Update Git timeline"
          : snapshots.length > 1 ? "Rebuild Git timeline" : "Import Git history",
  };
}

function historyHelp(info, snapshots, job, timeline) {
  if (activeHistoryStates.has(job.status)) {
    const progress = job.total_frames
      ? ` ${format.format(job.completed_frames || 0)}/${format.format(job.total_frames)}`
      : "";
    const commit = job.current_commit_subject
      ? ` Current commit: ${job.current_commit_subject}.`
      : "";
    return `${phaseLabel(job.status)}${progress} saved code maps.${commit} Current files, findings, and coding-agent tools remain available.`;
  }
  if (["failed", "cancelled"].includes(job.status)) {
    const reason = job.error ? ` ${job.error}` : "";
    return `History import ${job.status}.${reason} Completed code maps remain usable; retry continues without reading them again.`;
  }
  if (timeline.state === "stale") {
    return `The saved replay stops ${format.format(timeline.unmapped_tail_commits || 0)} commits before the current Git head, then shows the current working tree. Update the Git timeline before replaying if you want a smoother, representative sequence; the final jump is not a continuous animation.`;
  }
  if (info.total_commits > 0 && snapshots.length > 1) {
    const sampling = info.total_commits > info.analyzed_commits
      ? `${info.analyzed_commits} representative code maps across ${info.total_commits} commits in the repository's main Git history`
      : `${info.analyzed_commits} saved commit code maps`;
    return `${sampling}, from the first commit through the current commit. Saved maps are samples, not invented intermediate states; the slider labels how many commits were omitted between them.${workSummary(job.work)}`;
  }
  if (info.total_commits > 0) {
    return `Git contains ${info.total_commits} commits in its main history. Import them to replay how the code map changed from the first commit.`;
  }
  return "This mounted directory has no Git commit history, so only its current working tree can be shown.";
}

function jobDetails(job) {
  if (!job.id) return [];
  const work = job.work || {};
  const details = [
    ["State", phaseLabel(job.status)],
    ["Elapsed", duration(job.elapsed_seconds)],
  ];
  if (job.eta_seconds != null && activeHistoryStates.has(job.status)) {
    details.push(["Estimated remaining", duration(job.eta_seconds)]);
  }
  if (job.current_commit_sha) {
    details.push(["Current commit", `${String(job.current_commit_sha).slice(0, 10)} · ${job.current_commit_subject || "No subject"}`]);
  }
  if (job.current_commit_date) details.push(["Commit date", new Date(job.current_commit_date).toLocaleString()]);
  details.push(
    ["Changed files read", format.format(job.changed_files ?? work.source_reads ?? 0)],
    ["Files examined", format.format(job.analyzed_files ?? work.analyzed_files ?? 0)],
    ["Files whose links were checked again", format.format(job.re_resolved_files ?? work.relationship_sources_resolved ?? 0)],
    ["Files reused from an earlier map", format.format(job.reused_files ?? work.carried_forward ?? 0)],
    ["New facts saved in AnaxiIndex", format.format(job.rows_added || 0)],
    ["Saved index grew by", bytes(job.bytes_added || 0)],
  );
  if (job.last_complete_snapshot_id) {
    details.push(["Last usable saved scan", `#${job.last_complete_snapshot_id}`]);
  }
  return details;
}

function workSummary(work) {
  if (!Number.isFinite(work?.source_reads)) return "";
  return ` Last import read ${format.format(work.source_reads)} changed files, reused ${format.format(work.carried_forward || 0)} unchanged files, reused direct-link results for ${format.format(work.relationship_sources_reused || 0)} files, and checked links again for ${format.format(work.relationship_sources_resolved || 0)} files.`;
}

function phaseLabel(status) {
  const labels = {
    queued: "Waiting to start",
    enumerating: "Listing commits in Git history",
    importing: "Building code maps from Git history",
    finalizing: "Finishing the current saved scan",
    complete: "Complete",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  return labels[status] || "Not started";
}

function duration(value) {
  const seconds = Math.max(0, Number(value || 0));
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

function bytes(value) {
  const size = Math.max(0, Number(value || 0));
  if (size < 1024) return `${format.format(size)} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / 1024 ** 2).toFixed(1)} MiB`;
}
