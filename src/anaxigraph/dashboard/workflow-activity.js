// Requests and live model calls are separate: preparing or finishing uses no worker.
export function workflowRuns(data) {
  const worker = data.semantic?.worker || {};
  return worker.runs || [worker];
}

export function activeRuns(data) {
  return workflowRuns(data).filter(run => ["queued", "running"].includes(run.status));
}

export function requestedRun(data, workflow, step = null) {
  return activeRuns(data).find(run => run.workflow === workflow && (run.step || null) === step);
}

export function stepRun(data, step) {
  const runs = activeRuns(data);
  return runs.find(run => (run.active_step || run.step || data.client_step) === step)
    || runs.find(run => run.step === step);
}

export function liveWorkerCount(data) {
  return data.coverage?.live_jobs
    ? data.coverage.live_jobs.reduce((sum, row) => sum + (row.running || 0), 0)
    : data.semantic?.jobs?.running_live || 0;
}

export function activityLabel(data, flows) {
  const count = liveWorkerCount(data);
  if (count) return `${count} / ${data.execution.max_parallel_jobs} workers active`;
  const runs = activeRuns(data);
  if (!runs.length) return "";
  const steps = flows.flatMap(flow => flow.steps);
  const finished = run => run.phase === "finishing" || (run.step && steps.some(item => item.id === run.step && item.status === "complete"));
  if (runs.every(finished)) return "Results saved · finishing…";
  if (runs.some(run => run.phase === "waiting_retry")) return "Waiting for a scheduled retry…";
  if (runs.some(run => run.phase === "waiting_workers")) return "Waiting for shared workers…";
  if (runs.some(run => run.phase === "executing")) return "Saving worker results…";
  return "Preparing pending jobs…";
}

export function stepActivityLabel(run, retry, step) {
  if (run?.active_step && run.active_step !== step) return "Waiting for prerequisites";
  if (run?.phase === "finishing") return "Results saved";
  if (run?.phase === "waiting_workers") return "Waiting for shared workers";
  if (retry || run?.phase === "waiting_retry") return "Waiting to retry";
  return "Preparing jobs";
}
