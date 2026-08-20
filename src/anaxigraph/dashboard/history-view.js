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
  const active = activeHistoryStates.has(job.status);
  return {
    active,
    cancelRequested: Boolean(job.cancel_requested),
    help: historyHelp(info, snapshots, job),
    details: jobDetails(job),
    importDisabled: Number(info.total_commits || 0) < 1 || active,
    importLabel: active
      ? "Importing history…"
      : ["failed", "cancelled"].includes(job.status)
        ? "Retry / resume history"
        : snapshots.length > 1 ? "Rebuild Git timeline" : "Import Git history",
  };
}

function historyHelp(info, snapshots, job) {
  if (activeHistoryStates.has(job.status)) {
    const progress = job.total_frames
      ? ` ${format.format(job.completed_frames || 0)}/${format.format(job.total_frames)}`
      : "";
    const commit = job.current_commit_subject
      ? ` Current frame: ${job.current_commit_subject}.`
      : "";
    return `${phaseLabel(job.status)}${progress} graph frames.${commit} Current modules, findings, and agent tools remain available.`;
  }
  if (["failed", "cancelled"].includes(job.status)) {
    const reason = job.error ? ` ${job.error}` : "";
    return `History import ${job.status}.${reason} Completed frames remain usable; retry resumes without reprocessing them.`;
  }
  if (info.total_commits > 0 && snapshots.length > 1) {
    const sampling = info.total_commits > info.analyzed_commits
      ? `${info.analyzed_commits} representative graph frames across all ${info.total_commits} first-parent commits`
      : `${info.analyzed_commits} commit graph frames`;
    return `${sampling}, spanning the initial commit through HEAD. Scrub the timeline or replay the architecture biography.${workSummary(job.work)}`;
  }
  if (info.total_commits > 0) {
    return `Git contains ${info.total_commits} first-parent commits. Import its architecture biography to replay from the initial commit.`;
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
    ["Source reads", format.format(job.changed_files ?? work.source_reads ?? 0)],
    ["Analyzed", format.format(job.analyzed_files ?? work.analyzed_files ?? 0)],
    ["Re-resolved", format.format(job.re_resolved_files ?? work.relationship_sources_resolved ?? 0)],
    ["Reused", format.format(job.reused_files ?? work.carried_forward ?? 0)],
    ["Rows added", format.format(job.rows_added || 0)],
    ["Index growth", bytes(job.bytes_added || 0)],
  );
  if (job.last_complete_snapshot_id) {
    details.push(["Last usable snapshot", `#${job.last_complete_snapshot_id}`]);
  }
  return details;
}

function workSummary(work) {
  if (!Number.isFinite(work?.source_reads)) return "";
  return ` Last import: ${format.format(work.source_reads)} source reads, ${format.format(work.carried_forward || 0)} carried files, ${format.format(work.relationship_sources_reused || 0)} relationship sources reused, and ${format.format(work.relationship_sources_resolved || 0)} re-resolved.`;
}

function phaseLabel(status) {
  const labels = {
    queued: "Queued",
    enumerating: "Enumerating Git history",
    importing: "Importing Git history",
    finalizing: "Finalizing current snapshot",
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
