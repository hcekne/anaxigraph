// Explain the selected flow using its saved state, rather than another run's last message.
import { workflowState } from "/assets/workflow-model.js";
import { workflowRuns } from "/assets/workflow-activity.js";

export function workflowAction(flow, restart = false) {
  const state = workflowState(flow);
  if (restart && flow.id === "fresh-eyes") return "Run new Fresh Eyes review";
  if (state === "complete") return `${flow.name} is up to date`;
  if (flow.update || state === "refresh_needed") return `Update ${flow.name.toLowerCase()}`;
  if (["waiting", "interrupted", "failed", "queued"].includes(state)) return `Continue ${flow.name.toLowerCase()}`;
  return `Run full ${flow.name.toLowerCase()}`;
}

export function workflowRunNote(flow) {
  return `Runs the full ${flow.name} sequence. Reuses completed work and finishes what remains.`;
}

export function selectedFlowMessage(flow, data) {
  const run = workflowRuns(data).find(run => run.workflow === flow.id && run.snapshot_id === data.snapshot_id);
  if (run?.record?.status === "not_saved" && run.record.message) return `Analysis is saved locally. Shared architecture files were not saved: ${run.record.message}`;
  if (workflowState(flow) === "complete" && flow.unresolved) return `Catalogue review is saved; ${flow.unresolved} patterns remain unresolved. Open Patterns for the evidence and trade-offs. Completing a review does not endorse the architecture.`;
  if (workflowState(flow) === "complete") return `${flow.name} is up to date for saved scan ${data.snapshot_id}. Open any step to see its results.`;
  const remaining = flow.steps.filter(step => !["complete", "skipped"].includes(step.status));
  const blocked = remaining.find(step => step.status === "failed");
  if (blocked) {
    return blockedStepMessage(flow, blocked);
  }
  if (run?.error) return `${flow.name}: ${run.error}`;
  if (run?.message && run.status !== "complete") return `${run.message} Next: ${remaining[0]?.title || "check completion"}.`;
  return `${remaining.length} ${remaining.length === 1 ? "step remains" : "steps remain"}. ${remaining[0] ? `Next: ${remaining[0].title}.` : ""} Completed results are kept.`;
}

function blockedStepMessage(flow, blocked) {
  const error = blocked.poolErrors?.[0]?.error || blocked.jobs?.errors?.[0]?.error;
  return `${flow.name} stopped at “${blocked.title}”. ${error || "Open this step to inspect the reported issue and retry it."}`;
}
